"""
AWS Lambda entry point for CostRadar.

Two invocation modes:
  1. EventBridge scheduled event → runs the full detection pipeline
  2. API Gateway / Function URL → delegates to FastAPI via Mangum

Mangum translates the ASGI interface to Lambda's synchronous event/context
model, so the same FastAPI app handles both HTTP and scheduled triggers.
"""

import json
import logging
import os
import sys

# Ensure the backend package is importable when deployed as a Lambda layer
sys.path.insert(0, "/opt/python")

from dotenv import load_dotenv

load_dotenv()

from mangum import Mangum
from main import app
from cost_ingestion import fetch_and_store_costs, get_daily_totals
from anomaly_detection import run_anomaly_detection, filter_anomalies
from forecasting import run_forecast
from rightsizing import run_rightsizing
from alerting import process_anomaly_alerts
from dynamo_client import DynamoClient

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

# Mangum wraps the FastAPI ASGI app for API Gateway / Function URL invocations
_asgi_handler = Mangum(app, lifespan="off")


def _run_scheduled_detection() -> dict:
    """
    Full pipeline execution for the daily EventBridge trigger.
    Returns a summary dict that is captured in CloudWatch Logs.
    """
    logger.info("Scheduled detection run started")
    dynamo = DynamoClient()

    cost_records = fetch_and_store_costs(dynamo)
    anomaly_results = run_anomaly_detection(cost_records, dynamo)
    anomalies = filter_anomalies(anomaly_results)
    message_ids = process_anomaly_alerts(anomaly_results)

    daily_totals = get_daily_totals(cost_records)
    forecast_results = run_forecast(daily_totals, dynamo)
    rightsizing_results = run_rightsizing(dynamo)

    summary = {
        "status": "success",
        "cost_records_stored": len(cost_records),
        "anomalies_detected": len(anomalies),
        "alerts_sent": len(message_ids),
        "forecast_points": len(forecast_results),
        "rightsizing_evaluated": len(rightsizing_results),
    }
    logger.info("Scheduled detection complete: %s", json.dumps(summary))
    return summary


def handler(event: dict, context) -> dict:
    """
    Lambda handler — routes between scheduled pipeline and HTTP API based on
    whether the triggering event came from EventBridge or API Gateway.
    """
    source = event.get("source", "")
    detail_type = event.get("detail-type", "")

    # EventBridge scheduled events always carry source='aws.events'
    if source == "aws.events" or detail_type == "Scheduled Event":
        result = _run_scheduled_detection()
        return {
            "statusCode": 200,
            "body": json.dumps(result),
        }

    # All other events are treated as HTTP requests routed through Mangum
    return _asgi_handler(event, context)
