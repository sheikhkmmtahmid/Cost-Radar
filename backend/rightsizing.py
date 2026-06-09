"""
EC2 rightsizing recommendations based on 14-day CloudWatch CPU and memory metrics.
Memory metrics require the CloudWatch agent installed on each instance — instances
without memory data are evaluated on CPU alone.

Pricing tiers are approximate On-Demand US-East-1 rates for t3/m5 families.
We use a conservative savings estimate to avoid over-promising.
"""

import os
import logging
import uuid
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

from dynamo_client import DynamoClient

logger = logging.getLogger(__name__)

CPU_OVER_PROVISIONED_THRESHOLD = 20.0   # avg CPU < 20% → over-provisioned
CPU_UNDER_PROVISIONED_THRESHOLD = 80.0  # avg CPU > 80% → under-provisioned
LOOKBACK_DAYS = 14

# Approximate monthly On-Demand cost by instance type (USD), US-East-1.
# Instances not listed fall back to a generic per-vCPU estimate.
INSTANCE_MONTHLY_COST_USD: dict[str, float] = {
    "t3.nano": 3.80,
    "t3.micro": 7.59,
    "t3.small": 15.18,
    "t3.medium": 30.37,
    "t3.large": 60.74,
    "t3.xlarge": 121.47,
    "t3.2xlarge": 242.94,
    "m5.large": 69.12,
    "m5.xlarge": 138.24,
    "m5.2xlarge": 276.48,
    "m5.4xlarge": 552.96,
    "m5.8xlarge": 1105.92,
    "c5.large": 62.05,
    "c5.xlarge": 124.10,
    "c5.2xlarge": 248.20,
    "r5.large": 91.98,
    "r5.xlarge": 183.96,
    "r5.2xlarge": 367.92,
}

# Assumed savings if we downsize one tier (roughly 50% cost reduction per step)
DOWNSIZE_SAVINGS_FRACTION = 0.40


def _get_ec2_instances(ec2_client) -> list[dict]:
    """Return all running EC2 instances in the account."""
    instances = []
    paginator = ec2_client.get_paginator("describe_instances")
    try:
        for page in paginator.paginate(
            Filters=[{"Name": "instance-state-name", "Values": ["running"]}]
        ):
            for reservation in page["Reservations"]:
                for inst in reservation["Instances"]:
                    name_tag = next(
                        (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                        inst["InstanceId"],
                    )
                    instances.append(
                        {
                            "instance_id": inst["InstanceId"],
                            "instance_type": inst["InstanceType"],
                            "name": name_tag,
                        }
                    )
    except ClientError as exc:
        logger.error("describe_instances failed: %s", exc)
        raise
    return instances


def _get_average_metric(
    cw_client, instance_id: str, metric_name: str, namespace: str, stat: str = "Average"
) -> float | None:
    """
    Fetch the 14-day average of a CloudWatch metric for one instance.
    Returns None if no data points exist (metric not published).
    """
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=LOOKBACK_DAYS)

    try:
        response = cw_client.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric_name,
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=86400,  # daily datapoints to keep volume manageable
            Statistics=[stat],
        )
    except ClientError as exc:
        logger.warning("get_metric_statistics failed for %s/%s: %s", instance_id, metric_name, exc)
        return None

    datapoints = response.get("Datapoints", [])
    if not datapoints:
        return None

    return sum(dp[stat] for dp in datapoints) / len(datapoints)


def _classify_instance(avg_cpu: float | None, avg_mem: float | None) -> str:
    """
    Classify based on CPU first; memory acts as a tiebreaker when available.
    An instance is only over-provisioned if BOTH CPU and memory (when present)
    are below their thresholds — avoids wrongly flagging memory-heavy workloads.
    """
    if avg_cpu is None:
        return "unknown"

    if avg_cpu > CPU_UNDER_PROVISIONED_THRESHOLD:
        return "under-provisioned"

    if avg_cpu < CPU_OVER_PROVISIONED_THRESHOLD:
        # If memory is available and high, don't flag as over-provisioned
        if avg_mem is not None and avg_mem > CPU_OVER_PROVISIONED_THRESHOLD:
            return "right-sized"
        return "over-provisioned"

    return "right-sized"


def _estimate_monthly_savings(instance_type: str) -> float:
    """
    Estimate the monthly dollar saving from downsizing one tier.
    Uses the known monthly cost table; defaults to 0 if type is unknown.
    """
    monthly_cost = INSTANCE_MONTHLY_COST_USD.get(instance_type, 0.0)
    return round(monthly_cost * DOWNSIZE_SAVINGS_FRACTION, 2)


def run_rightsizing(dynamo: DynamoClient | None = None) -> list[dict]:
    """
    Evaluate all running EC2 instances and return rightsizing recommendations.
    Results are stored in DynamoDB and returned to the caller for immediate use.
    """
    if dynamo is None:
        dynamo = DynamoClient()

    region = os.environ["AWS_REGION"]
    ec2_client = boto3.client("ec2", region_name=region)
    cw_client = boto3.client("cloudwatch", region_name=region)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + f"_{uuid.uuid4().hex[:8]}"
    instances = _get_ec2_instances(ec2_client)

    if not instances:
        logger.info("No running EC2 instances found; rightsizing skipped")
        return []

    results: list[dict] = []

    for inst in instances:
        instance_id = inst["instance_id"]
        instance_type = inst["instance_type"]

        avg_cpu = _get_average_metric(
            cw_client, instance_id, "CPUUtilization", "AWS/EC2"
        )
        # CWAgent namespace for memory — only available when CloudWatch agent is installed
        avg_mem = _get_average_metric(
            cw_client, instance_id, "mem_used_percent", "CWAgent"
        )

        classification = _classify_instance(avg_cpu, avg_mem)
        savings = (
            _estimate_monthly_savings(instance_type)
            if classification == "over-provisioned"
            else 0.0
        )

        record = {
            "instance_id": instance_id,
            "instance_type": instance_type,
            "name": inst["name"],
            "avg_cpu_percent": avg_cpu,
            "avg_memory_percent": avg_mem,
            "classification": classification,
            "estimated_monthly_savings_usd": savings,
        }
        results.append(record)
        dynamo.put_rightsizing_record(run_id=run_id, record=record)

        logger.info(
            "Instance %s (%s): CPU=%.1f%% MEM=%s → %s (save $%.2f/mo)",
            instance_id,
            instance_type,
            avg_cpu or 0.0,
            f"{avg_mem:.1f}%" if avg_mem is not None else "N/A",
            classification,
            savings,
        )

    return results
