"""
Pulls last 90 days of daily AWS spend per service from Cost Explorer
and writes records to DynamoDB. Designed to run as a Lambda or CLI job.
"""

import os
import logging
from datetime import date, timedelta

import boto3
from botocore.exceptions import ClientError

from dynamo_client import DynamoClient

logger = logging.getLogger(__name__)


def _date_range(start: date, end: date) -> tuple[str, str]:
    """Cost Explorer expects YYYY-MM-DD strings and end is exclusive."""
    return start.isoformat(), (end + timedelta(days=1)).isoformat()


def fetch_and_store_costs(dynamo: DynamoClient | None = None) -> list[dict]:
    """
    Pull 90 days of daily cost data grouped by AWS service from Cost Explorer.
    Returns raw records so the caller can chain into anomaly detection without
    reading them back from DynamoDB.
    """
    if dynamo is None:
        dynamo = DynamoClient()

    ce_client = boto3.client("ce", region_name=os.environ["AWS_REGION"])

    end_date = date.today()
    start_date = end_date - timedelta(days=90)
    start_str, end_str = _date_range(start_date, end_date)

    logger.info("Fetching costs from %s to %s", start_str, end_str)

    try:
        response = ce_client.get_cost_and_usage(
            TimePeriod={"Start": start_str, "End": end_str},
            Granularity="DAILY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.error("Cost Explorer GetCostAndUsage failed [%s]: %s", error_code, exc)
        raise

    records: list[dict] = []

    for result_by_time in response["ResultsByTime"]:
        period_start = result_by_time["TimePeriod"]["Start"]

        for group in result_by_time["Groups"]:
            service_name = group["Keys"][0]
            amount_str = group["Metrics"]["UnblendedCost"]["Amount"]
            cost_usd = float(amount_str)

            # Skip zero-cost lines — they add noise without signal
            if cost_usd == 0.0:
                continue

            records.append(
                {
                    "date": period_start,
                    "service": service_name,
                    "cost_usd": cost_usd,
                }
            )

            dynamo.put_cost_record(
                date=period_start,
                service=service_name,
                cost_usd=cost_usd,
            )

    logger.info("Stored %d cost records across %d time periods", len(records), len(response["ResultsByTime"]))
    return records


def get_daily_totals(records: list[dict]) -> list[dict]:
    """
    Aggregate per-service records into daily totals for forecasting.
    Returns list of {date, total_cost_usd} dicts sorted by date.
    """
    totals: dict[str, float] = {}
    for rec in records:
        totals[rec["date"]] = totals.get(rec["date"], 0.0) + rec["cost_usd"]

    return [{"date": d, "total_cost_usd": v} for d, v in sorted(totals.items())]
