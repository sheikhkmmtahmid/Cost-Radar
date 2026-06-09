"""
SNS alerting for cost anomalies that exceed the configured score threshold.
Publishes a structured JSON payload so downstream subscribers (email, Lambda,
Slack webhook) can parse fields without scraping a human-readable string.
"""

import json
import os
import logging
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Anomaly scores are negated IsolationForest decision_function values.
# 0.1 corresponds roughly to the boundary IsolationForest uses internally;
# values above this indicate clear outliers rather than borderline cases.
DEFAULT_ALERT_THRESHOLD = float(os.environ.get("ANOMALY_ALERT_THRESHOLD", "0.1"))


def publish_anomaly_alert(
    service: str,
    date: str,
    cost_usd: float,
    anomaly_score: float,
    sns_topic_arn: str | None = None,
) -> str | None:
    """
    Publish a single anomaly alert to SNS.
    Returns the SNS MessageId on success, or None if publishing is skipped
    (e.g. topic ARN not configured, which is valid in local dev).
    """
    topic_arn = sns_topic_arn or os.environ.get("SNS_TOPIC_ARN")
    if not topic_arn:
        logger.info("SNS_TOPIC_ARN not set — alert suppressed (local dev mode)")
        return None

    region = os.environ["AWS_REGION"]
    sns_client = boto3.client("sns", region_name=region)

    payload = {
        "source": "CostRadar",
        "alert_type": "cost_anomaly",
        "service": service,
        "date": date,
        "cost_usd": round(cost_usd, 4),
        "anomaly_score": round(anomaly_score, 6),
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }

    subject = f"[CostRadar] Cost anomaly detected: {service} on {date}"

    try:
        response = sns_client.publish(
            TopicArn=topic_arn,
            Subject=subject,
            Message=json.dumps(payload, indent=2),
            MessageAttributes={
                "service": {
                    "DataType": "String",
                    "StringValue": service,
                },
                "alert_type": {
                    "DataType": "String",
                    "StringValue": "cost_anomaly",
                },
            },
        )
        message_id = response["MessageId"]
        logger.info("Alert published for %s on %s: MessageId=%s", service, date, message_id)
        return message_id
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.error("SNS publish failed [%s] for %s/%s: %s", error_code, service, date, exc)
        raise


def process_anomaly_alerts(
    anomaly_results: list[dict],
    threshold: float = DEFAULT_ALERT_THRESHOLD,
    sns_topic_arn: str | None = None,
) -> list[str]:
    """
    Filter anomaly results by score threshold and publish an SNS alert for each.
    Returns list of SNS MessageIds for all successfully published alerts.
    """
    message_ids: list[str] = []

    for result in anomaly_results:
        if not result.get("is_anomaly"):
            continue

        score = result.get("anomaly_score", 0.0)
        if score < threshold:
            # is_anomaly=True but score below threshold — suppress noisy alerts
            continue

        msg_id = publish_anomaly_alert(
            service=result["service"],
            date=result["date"],
            cost_usd=result["cost_usd"],
            anomaly_score=score,
            sns_topic_arn=sns_topic_arn,
        )
        if msg_id:
            message_ids.append(msg_id)

    logger.info(
        "Alert processing complete: %d anomalies evaluated, %d alerts sent",
        sum(1 for r in anomaly_results if r.get("is_anomaly")),
        len(message_ids),
    )
    return message_ids
