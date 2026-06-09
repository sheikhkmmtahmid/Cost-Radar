"""
DynamoDB client — centralises table access and common read/write patterns.
Every other module gets a typed interface instead of raw boto3 calls.
"""

import os
import logging
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


def _to_decimal(obj):
    # DynamoDB rejects float — every numeric value must be Decimal
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: _to_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_decimal(i) for i in obj]
    return obj


def _from_decimal(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _from_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_from_decimal(i) for i in obj]
    return obj


class DynamoClient:
    def __init__(self):
        region = os.environ["AWS_REGION"]
        self._resource = boto3.resource("dynamodb", region_name=region)
        self.costs_table = self._resource.Table(os.environ["DYNAMODB_COSTS_TABLE"])
        self.anomalies_table = self._resource.Table(os.environ["DYNAMODB_ANOMALIES_TABLE"])
        self.forecast_table = self._resource.Table(os.environ["DYNAMODB_FORECAST_TABLE"])
        self.rightsizing_table = self._resource.Table(os.environ["DYNAMODB_RIGHTSIZING_TABLE"])

    # ------------------------------------------------------------------
    # Cost data
    # ------------------------------------------------------------------

    def put_cost_record(self, date: str, service: str, cost_usd: float) -> None:
        try:
            self.costs_table.put_item(
                Item=_to_decimal({
                    "pk": f"SERVICE#{service}",
                    "sk": f"DATE#{date}",
                    "service": service,
                    "date": date,
                    "cost_usd": cost_usd,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
            )
        except ClientError as exc:
            logger.error("put_cost_record failed %s/%s: %s", service, date, exc)
            raise

    def get_cost_records(self, service: str) -> list[dict]:
        try:
            response = self.costs_table.query(
                KeyConditionExpression=boto3.dynamodb.conditions.Key("pk").eq(f"SERVICE#{service}")
            )
            return sorted(
                [_from_decimal(i) for i in response["Items"]],
                key=lambda r: r["date"],
            )
        except ClientError as exc:
            logger.error("get_cost_records failed %s: %s", service, exc)
            raise

    def get_all_cost_records(self) -> list[dict]:
        try:
            response = self.costs_table.scan()
            items = response["Items"]
            while "LastEvaluatedKey" in response:
                response = self.costs_table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
                items.extend(response["Items"])
            return [_from_decimal(i) for i in items]
        except ClientError as exc:
            logger.error("get_all_cost_records failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Anomalies
    # ------------------------------------------------------------------

    def put_anomaly(self, run_id: str, record: dict) -> None:
        """Accepts the full result dict from anomaly_detection so the
        schema stays in one place instead of being split across two files."""
        try:
            item = {
                "pk": f"RUN#{run_id}",
                "sk": f"SERVICE#{record['service']}#DATE#{record['date']}",
                **record,
            }
            self.anomalies_table.put_item(Item=_to_decimal(item))
        except ClientError as exc:
            logger.error("put_anomaly failed %s/%s: %s", record.get("service"), record.get("date"), exc)
            raise

    def get_latest_anomalies(self) -> list[dict]:
        """Returns records flagged by either model from the most recent run."""
        try:
            # pull everything flagged by IF or Z-score
            response = self.anomalies_table.scan(
                FilterExpression=(
                    boto3.dynamodb.conditions.Attr("is_anomaly").eq(True)
                    | boto3.dynamodb.conditions.Attr("z_score_flagged").eq(True)
                )
            )
            items = response["Items"]
            while "LastEvaluatedKey" in response:
                response = self.anomalies_table.scan(
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                    FilterExpression=(
                        boto3.dynamodb.conditions.Attr("is_anomaly").eq(True)
                        | boto3.dynamodb.conditions.Attr("z_score_flagged").eq(True)
                    ),
                )
                items.extend(response["Items"])

            if not items:
                return []

            items = [_from_decimal(i) for i in items]
            latest_run = max(items, key=lambda r: r.get("detected_at", ""))["run_id"]
            return [i for i in items if i["run_id"] == latest_run]
        except ClientError as exc:
            logger.error("get_latest_anomalies failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Forecast
    # ------------------------------------------------------------------

    def put_forecast_record(
        self, run_id: str, date: str, yhat: float, yhat_lower: float, yhat_upper: float
    ) -> None:
        try:
            self.forecast_table.put_item(
                Item=_to_decimal({
                    "pk": f"RUN#{run_id}",
                    "sk": f"DATE#{date}",
                    "run_id": run_id,
                    "date": date,
                    "yhat": yhat,
                    "yhat_lower": yhat_lower,
                    "yhat_upper": yhat_upper,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            )
        except ClientError as exc:
            logger.error("put_forecast_record failed %s: %s", date, exc)
            raise

    def put_forecast_metrics(self, run_id: str, metrics: dict) -> None:
        """Stores MAE/MAPE/budget info as a special item alongside the forecast points."""
        try:
            self.forecast_table.put_item(
                Item=_to_decimal({
                    "pk": f"RUN#{run_id}",
                    "sk": "METRICS",
                    "run_id": run_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    **metrics,
                })
            )
        except ClientError as exc:
            logger.error("put_forecast_metrics failed: %s", exc)
            raise

    def get_latest_forecast(self) -> list[dict]:
        try:
            response = self.forecast_table.scan()
            items = response["Items"]
            while "LastEvaluatedKey" in response:
                response = self.forecast_table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
                items.extend(response["Items"])

            if not items:
                return []

            items = [_from_decimal(i) for i in items]
            # exclude the METRICS sentinel item
            points = [i for i in items if i.get("sk", "").startswith("DATE#")]
            if not points:
                return []

            latest_run = max(points, key=lambda r: r["created_at"])["run_id"]
            return sorted(
                [p for p in points if p["run_id"] == latest_run],
                key=lambda r: r["date"],
            )
        except ClientError as exc:
            logger.error("get_latest_forecast failed: %s", exc)
            raise

    def get_latest_forecast_metrics(self) -> dict | None:
        try:
            response = self.forecast_table.scan(
                FilterExpression=boto3.dynamodb.conditions.Attr("sk").eq("METRICS")
            )
            items = response["Items"]
            while "LastEvaluatedKey" in response:
                response = self.forecast_table.scan(
                    ExclusiveStartKey=response["LastEvaluatedKey"],
                    FilterExpression=boto3.dynamodb.conditions.Attr("sk").eq("METRICS"),
                )
                items.extend(response["Items"])

            if not items:
                return None

            latest = max([_from_decimal(i) for i in items], key=lambda r: r["created_at"])
            latest.pop("pk", None)
            latest.pop("sk", None)
            return latest
        except ClientError as exc:
            logger.error("get_latest_forecast_metrics failed: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Rightsizing
    # ------------------------------------------------------------------

    def put_rightsizing_record(self, run_id: str, record: dict) -> None:
        try:
            item = {
                "pk": f"RUN#{run_id}",
                "sk": f"INSTANCE#{record['instance_id']}",
                "run_id": run_id,
                **record,
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }
            self.rightsizing_table.put_item(Item=_to_decimal(item))
        except ClientError as exc:
            logger.error("put_rightsizing_record failed %s: %s", record.get("instance_id"), exc)
            raise

    def get_latest_rightsizing(self) -> list[dict]:
        try:
            response = self.rightsizing_table.scan()
            items = response["Items"]
            while "LastEvaluatedKey" in response:
                response = self.rightsizing_table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
                items.extend(response["Items"])

            if not items:
                return []

            items = [_from_decimal(i) for i in items]
            latest_run = max(items, key=lambda r: r["evaluated_at"])["run_id"]
            return sorted(
                [i for i in items if i["run_id"] == latest_run],
                key=lambda r: r.get("estimated_monthly_savings_usd", 0),
                reverse=True,
            )
        except ClientError as exc:
            logger.error("get_latest_rightsizing failed: %s", exc)
            raise
