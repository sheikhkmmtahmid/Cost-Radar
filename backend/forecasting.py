"""
30-day cost forecast using Prophet, with in-sample accuracy metrics
and optional monthly budget projection.

Prophet handles weekly seasonality (lower spend on weekends) without
any manual feature engineering, which is why it fits billing data well.
"""

import calendar
import logging
import os
import uuid
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
from prophet import Prophet

from dynamo_client import DynamoClient

logger = logging.getLogger(__name__)

FORECAST_DAYS = 30
MONTHLY_BUDGET_USD = float(os.environ.get("MONTHLY_BUDGET_USD", "0"))


def _accuracy_metrics(actual_df: pd.DataFrame, forecast_df: pd.DataFrame) -> dict:
    """
    In-sample fit quality. Prophet fits the training window, so MAE here
    tells us how closely the model tracks historical variation — not future
    accuracy, but a useful sanity check on whether the model is badly over
    or under-smoothing.
    """
    merged = actual_df.merge(forecast_df[["ds", "yhat"]], on="ds", how="inner")
    if len(merged) < 2:
        return {}

    actual = merged["y"].values
    predicted = merged["yhat"].values

    mae = float(np.mean(np.abs(actual - predicted)))

    # skip near-zero actuals to avoid inflating MAPE
    nonzero = actual > 0.01
    mape = (
        float(np.mean(np.abs((actual[nonzero] - predicted[nonzero]) / actual[nonzero])) * 100)
        if nonzero.sum() > 0 else None
    )

    ss_res = np.sum((actual - predicted) ** 2)
    ss_tot = np.sum((actual - np.mean(actual)) ** 2)
    r_squared = float(1 - ss_res / ss_tot) if ss_tot > 0 else None

    return {
        "mae": round(mae, 4),
        "mape": round(mape, 2) if mape is not None else None,
        "r_squared": round(r_squared, 4) if r_squared is not None else None,
        "data_points_used": int(len(merged)),
    }


def _budget_projection(
    forecast_df: pd.DataFrame,
    daily_totals: list[dict],
    budget: float,
) -> dict | None:
    if budget <= 0:
        return None

    today = date.today()
    month_start = today.replace(day=1).isoformat()
    _, last_day = calendar.monthrange(today.year, today.month)
    month_end = today.replace(day=last_day)

    actual_mtd = sum(
        r["total_cost_usd"]
        for r in daily_totals
        if month_start <= r["date"] <= today.isoformat()
    )

    future_in_month = forecast_df[
        (forecast_df["ds"].dt.date > today)
        & (forecast_df["ds"].dt.date <= month_end)
    ]
    forecast_remaining = float(future_in_month["yhat"].clip(lower=0).sum())
    projected_total = actual_mtd + forecast_remaining
    overage = max(0.0, projected_total - budget)

    # find the day cumulative spend first crosses the budget line
    breach_day = None
    running = actual_mtd
    for _, row in future_in_month.iterrows():
        running += max(0.0, row["yhat"])
        if running >= budget:
            breach_day = row["ds"].strftime("%Y-%m-%d")
            break

    if projected_total > budget:
        status = "over_budget"
    elif projected_total > budget * 0.85:
        # within 15% of the limit — worth flagging early
        status = "at_risk"
    else:
        status = "under_budget"

    return {
        "monthly_budget_usd": budget,
        "projected_month_total": round(projected_total, 2),
        "actual_month_to_date": round(actual_mtd, 2),
        "forecast_remaining": round(forecast_remaining, 2),
        "breach_day": breach_day,
        "overage_usd": round(overage, 2),
        "status": status,
    }


def run_forecast(
    daily_totals: list[dict], dynamo: DynamoClient | None = None
) -> tuple[list[dict], dict]:
    """
    Returns (forecast_points, metadata) where metadata contains accuracy
    metrics and budget projection. Callers that only want the points can
    just index [0].
    """
    if dynamo is None:
        dynamo = DynamoClient()

    if len(daily_totals) < 5:
        raise ValueError(f"Need at least 5 days of history; got {len(daily_totals)}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + f"_{uuid.uuid4().hex[:8]}"

    df = pd.DataFrame(daily_totals).rename(columns={"date": "ds", "total_cost_usd": "y"})
    df["ds"] = pd.to_datetime(df["ds"])

    model = Prophet(
        daily_seasonality=False,
        weekly_seasonality=True,
        yearly_seasonality=False,
        interval_width=0.95,
        uncertainty_samples=500,
    )
    model.fit(df)

    future_df = model.make_future_dataframe(periods=FORECAST_DAYS, freq="D")
    forecast_df = model.predict(future_df)

    accuracy = _accuracy_metrics(df, forecast_df)
    budget_info = _budget_projection(forecast_df, daily_totals, MONTHLY_BUDGET_USD)

    points: list[dict] = []
    for _, row in forecast_df.iterrows():
        date_str = row["ds"].strftime("%Y-%m-%d")
        yhat = max(0.0, float(row["yhat"]))
        yhat_lower = max(0.0, float(row["yhat_lower"]))
        yhat_upper = float(row["yhat_upper"])

        record = {
            "run_id": run_id,
            "date": date_str,
            "yhat": yhat,
            "yhat_lower": yhat_lower,
            "yhat_upper": yhat_upper,
        }
        points.append(record)
        dynamo.put_forecast_record(
            run_id=run_id,
            date=date_str,
            yhat=yhat,
            yhat_lower=yhat_lower,
            yhat_upper=yhat_upper,
        )

    metadata = {
        "accuracy": accuracy or None,
        "budget": budget_info,
    }
    dynamo.put_forecast_metrics(run_id=run_id, metrics=metadata)

    logger.info(
        "Forecast %s: %d points, MAE=%.4f, MAPE=%s, budget_status=%s",
        run_id,
        len(points),
        accuracy.get("mae", 0),
        accuracy.get("mape"),
        budget_info.get("status") if budget_info else "not_configured",
    )

    return points, metadata
