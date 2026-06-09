"""
CostRadar FastAPI backend.
"""

import logging
import os
import pathlib
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from dynamo_client import DynamoClient
from cost_ingestion import fetch_and_store_costs, get_daily_totals
from anomaly_detection import run_anomaly_detection, filter_anomalies, build_comparison_stats
from forecasting import run_forecast
from rightsizing import run_rightsizing
from alerting import process_anomaly_alerts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

_dynamo: DynamoClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _dynamo
    _dynamo = DynamoClient()
    logger.info("DynamoDB client initialised")
    yield


app = FastAPI(title="CostRadar API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


def get_dynamo() -> DynamoClient:
    if _dynamo is None:
        raise HTTPException(status_code=503, detail="DynamoDB client not initialised")
    return _dynamo


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class CostRecord(BaseModel):
    date: str
    service: str
    cost_usd: float


class AnomalyRecord(BaseModel):
    run_id: str
    service: str
    date: str
    cost_usd: float
    anomaly_score: float
    is_anomaly: bool
    z_score: float | None = None
    z_score_flagged: bool | None = None
    consensus: bool | None = None
    explanation: str | None = None
    historical_mean: float | None = None
    historical_std: float | None = None
    percentile: int | None = None
    detected_at: str | None = None


class ForecastPoint(BaseModel):
    date: str
    yhat: float
    yhat_lower: float
    yhat_upper: float


class ForecastAccuracy(BaseModel):
    mae: float | None = None
    mape: float | None = None
    r_squared: float | None = None
    data_points_used: int | None = None


class BudgetAnalysis(BaseModel):
    monthly_budget_usd: float
    projected_month_total: float
    actual_month_to_date: float
    forecast_remaining: float
    breach_day: str | None = None
    overage_usd: float
    status: str


class ForecastResponse(BaseModel):
    points: list[ForecastPoint]
    accuracy: ForecastAccuracy | None = None
    budget: BudgetAnalysis | None = None


class ComparisonStats(BaseModel):
    per_service: list[dict]
    total_if: int
    total_z_score: int
    total_consensus: int
    agreement_rate_pct: float


class RightsizingRecord(BaseModel):
    instance_id: str
    instance_type: str
    name: str
    avg_cpu_percent: float | None = None
    avg_memory_percent: float | None = None
    classification: str
    estimated_monthly_savings_usd: float


class DetectionResponse(BaseModel):
    cost_records_stored: int
    anomalies_detected: int
    alerts_sent: int
    forecast_points: int
    rightsizing_evaluated: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok", "service": "costradar-api"}


@app.get("/costs", response_model=list[CostRecord], tags=["costs"])
def list_costs():
    dynamo = get_dynamo()
    try:
        records = dynamo.get_all_cost_records()
    except Exception as exc:
        logger.error("Failed to retrieve costs: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve cost data")
    return sorted(records, key=lambda r: r["date"], reverse=True)


@app.get("/anomalies", response_model=list[AnomalyRecord], tags=["anomalies"])
def list_anomalies():
    dynamo = get_dynamo()
    try:
        return dynamo.get_latest_anomalies()
    except Exception as exc:
        logger.error("Failed to retrieve anomalies: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve anomaly data")


@app.get("/forecast", response_model=ForecastResponse, tags=["forecast"])
def list_forecast():
    dynamo = get_dynamo()
    try:
        points = dynamo.get_latest_forecast()
        raw_metrics = dynamo.get_latest_forecast_metrics() or {}
    except Exception as exc:
        logger.error("Failed to retrieve forecast: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve forecast data")

    accuracy_data = raw_metrics.get("accuracy")
    budget_data = raw_metrics.get("budget")

    return ForecastResponse(
        points=points,
        accuracy=ForecastAccuracy(**accuracy_data) if accuracy_data else None,
        budget=BudgetAnalysis(**budget_data) if budget_data else None,
    )


@app.get("/anomalies/comparison", response_model=ComparisonStats, tags=["anomalies"])
def anomaly_comparison():
    """Model comparison stats derived from the latest anomaly run."""
    dynamo = get_dynamo()
    try:
        all_records = dynamo.get_latest_anomalies()
    except Exception as exc:
        logger.error("Failed to retrieve anomaly comparison: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve comparison data")
    return build_comparison_stats(all_records)


@app.get("/rightsizing", response_model=list[RightsizingRecord], tags=["rightsizing"])
def list_rightsizing():
    dynamo = get_dynamo()
    try:
        return dynamo.get_latest_rightsizing()
    except Exception as exc:
        logger.error("Failed to retrieve rightsizing: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve rightsizing data")


@app.get("/alerts", tags=["alerts"])
def list_alerts():
    dynamo = get_dynamo()
    try:
        anomalies = dynamo.get_latest_anomalies()
    except Exception as exc:
        logger.error("Failed to retrieve alerts: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to retrieve alert data")
    return {
        "total_anomalies": len(anomalies),
        "services_affected": list({a["service"] for a in anomalies}),
        "latest_anomalies": anomalies[:10],
    }


@app.post("/detect", response_model=DetectionResponse, tags=["ops"])
def run_detection_pipeline():
    dynamo = get_dynamo()

    try:
        cost_records = fetch_and_store_costs(dynamo)
    except Exception as exc:
        logger.error("Cost ingestion failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Cost ingestion failed: {exc}")

    try:
        anomaly_results = run_anomaly_detection(cost_records, dynamo)
    except Exception as exc:
        logger.error("Anomaly detection failed: %s", exc)
        raise HTTPException(status_code=500, detail=f"Anomaly detection failed: {exc}")

    anomalies = filter_anomalies(anomaly_results)

    try:
        message_ids = process_anomaly_alerts(anomaly_results)
    except Exception as exc:
        logger.warning("Alert publishing failed (non-fatal): %s", exc)
        message_ids = []

    try:
        daily_totals = get_daily_totals(cost_records)
        forecast_points, _ = run_forecast(daily_totals, dynamo)
    except Exception as exc:
        logger.warning("Forecasting skipped — not enough history: %s", exc)
        forecast_points = []

    try:
        rightsizing_results = run_rightsizing(dynamo)
    except Exception as exc:
        logger.warning("Rightsizing skipped (non-fatal): %s", exc)
        rightsizing_results = []

    return {
        "cost_records_stored": len(cost_records),
        "anomalies_detected": len(anomalies),
        "alerts_sent": len(message_ids),
        "forecast_points": len(forecast_points),
        "rightsizing_evaluated": len(rightsizing_results),
    }


# Serve the built React frontend — must be mounted after all API routes
_static_dir = pathlib.Path(__file__).parent / "static"
if _static_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")
