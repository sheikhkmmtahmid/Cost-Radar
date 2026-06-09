"""
Mock API server — no AWS credentials needed.
Run with: python mock_server.py

Serves realistic fake data including the new explainability fields,
model comparison stats, forecast accuracy metrics, and budget projection.
Works identically to the real server from the frontend's perspective.
"""

import random
from datetime import date, timedelta

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

rng = random.Random(42)

app = FastAPI(title="CostRadar Mock API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])

TODAY = date.today()

SERVICES = [
    ("Amazon EC2",        18.0, 3.5),
    ("Amazon RDS",         9.0, 1.5),
    ("Amazon S3",          3.2, 0.7),
    ("AWS Lambda",         1.1, 0.3),
    ("Amazon CloudFront",  2.1, 0.5),
    ("AWS Data Transfer",  0.9, 0.2),
]

SPIKES = {
    69: ("Amazon EC2",  85.40),
    44: ("Amazon RDS",  47.20),
    21: ("Amazon S3",   28.60),
    14: ("Amazon EC2",  72.80),
     7: ("AWS Lambda",  17.90),
}


def _day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _is_weekend(offset: int) -> bool:
    return (TODAY + timedelta(days=offset)).weekday() >= 5


def _build_costs() -> list[dict]:
    costs = []
    spikes = {-(k): v for k, v in SPIKES.items()}
    for i in range(-89, 1):
        d = _day(i)
        for service, base, noise in SERVICES:
            val = max(0.01, rng.gauss(base, noise) * (0.6 if _is_weekend(i) else 1.0))
            if i in spikes and spikes[i][0] == service:
                val = spikes[i][1]
            costs.append({"date": d, "service": service, "cost_usd": round(val, 4)})
    return sorted(costs, key=lambda r: r["date"], reverse=True)


def _build_anomalies() -> list[dict]:
    run_id = "20260605T080000_demo01"
    spike_meta = [
        (-69, "Amazon EC2",  85.40, 18.0, 3.5, 0.312, 4.2,  True,  True,  99),
        (-44, "Amazon RDS",  47.20,  9.0, 1.5, 0.278, 3.9,  True,  True,  98),
        (-21, "Amazon S3",   28.60,  3.2, 0.7, 0.241, 3.1,  True,  True,  97),
        (-14, "Amazon EC2",  72.80, 18.0, 3.5, 0.295, 3.8,  True,  True,  98),
        ( -7, "AWS Lambda",  17.90,  1.1, 0.3, 0.189, 2.6,  True,  False, 96),
    ]
    records = []
    for offset, service, cost, mean, std, score, z, if_flag, z_flag, pct in spike_meta:
        consensus = if_flag and z_flag
        direction = "above"
        rank = f"top {100 - pct}%"
        delta = abs(cost - mean)
        impact = f"That's ${delta:.2f} more than the typical daily spend for this service."
        if consensus:
            conf = "Both models flagged this — high confidence."
        elif if_flag:
            conf = "Isolation Forest only — Z-score within normal range."
        else:
            conf = "Z-score flagged — Isolation Forest considers it borderline."
        explanation = (
            f"${cost:.2f} sits {z:.1f}σ {direction} the service mean (${mean:.2f}), "
            f"placing it in the {rank} of recorded values. {impact} {conf}"
        )
        records.append({
            "run_id": run_id,
            "service": service,
            "date": _day(offset),
            "cost_usd": cost,
            "anomaly_score": score,
            "is_anomaly": if_flag,
            "z_score": round(z, 4),
            "z_score_flagged": z_flag,
            "consensus": consensus,
            "explanation": explanation,
            "historical_mean": mean,
            "historical_std": std,
            "percentile": pct,
            "detected_at": "2026-06-05T08:00:00+00:00",
        })
    # sort: consensus first, then by date descending
    records.sort(key=lambda r: r["date"], reverse=True)
    records.sort(key=lambda r: 0 if r["consensus"] else (1 if r["is_anomaly"] else 2))
    return records


def _build_forecast() -> dict:
    run_id = "20260605T080000_demo01"
    base = 34.5
    points = []
    for i in range(-89, 31):
        d = _day(i)
        trend = i * 0.025
        season = -3.2 if _is_weekend(i) else 0.0
        yhat = max(0.0, base + trend + season + rng.gauss(0, 0.4))
        ci = 2.8 + max(0, i) * 0.14
        points.append({
            "run_id": run_id,
            "date": d,
            "yhat": round(yhat, 4),
            "yhat_lower": round(max(0.0, yhat - ci), 4),
            "yhat_upper": round(yhat + ci, 4),
        })

    # realistic in-sample fit metrics
    accuracy = {
        "mae": 1.84,
        "mape": 5.32,
        "r_squared": 0.91,
        "data_points_used": 90,
    }

    # budget projection based on mock forecast
    today_str = TODAY.isoformat()
    future = [p for p in points if p["date"] > today_str]
    import calendar
    _, last_day = calendar.monthrange(TODAY.year, TODAY.month)
    month_end = TODAY.replace(day=last_day).isoformat()
    month_start = TODAY.replace(day=1).isoformat()

    actual_mtd = sum(
        p["yhat"] for p in points
        if month_start <= p["date"] <= today_str
    )
    forecast_remaining = sum(
        p["yhat"] for p in future if p["date"] <= month_end
    )
    projected = actual_mtd + forecast_remaining
    budget = 500.0

    breach_day = None
    running = actual_mtd
    for p in future:
        if p["date"] > month_end:
            break
        running += p["yhat"]
        if running >= budget and breach_day is None:
            breach_day = p["date"]

    status = "over_budget" if projected > budget else ("at_risk" if projected > budget * 0.85 else "under_budget")

    budget_info = {
        "monthly_budget_usd": budget,
        "projected_month_total": round(projected, 2),
        "actual_month_to_date": round(actual_mtd, 2),
        "forecast_remaining": round(forecast_remaining, 2),
        "breach_day": breach_day,
        "overage_usd": round(max(0.0, projected - budget), 2),
        "status": status,
    }

    return {"points": points, "accuracy": accuracy, "budget": budget_info}


def _build_comparison() -> dict:
    return {
        "per_service": [
            {"service": "Amazon EC2",       "if_count": 2, "z_count": 2, "consensus_count": 2, "total": 90},
            {"service": "Amazon RDS",       "if_count": 1, "z_count": 1, "consensus_count": 1, "total": 90},
            {"service": "Amazon S3",        "if_count": 1, "z_count": 1, "consensus_count": 1, "total": 90},
            {"service": "AWS Lambda",       "if_count": 1, "z_count": 0, "consensus_count": 0, "total": 90},
            {"service": "Amazon CloudFront","if_count": 0, "z_count": 0, "consensus_count": 0, "total": 90},
        ],
        "total_if": 5,
        "total_z_score": 4,
        "total_consensus": 4,
        "agreement_rate_pct": 80.0,
    }


def _build_rightsizing() -> list[dict]:
    return [
        {"instance_id": "i-0a1b2c3d4e5f6789", "instance_type": "m5.xlarge",  "name": "api-server-prod",  "avg_cpu_percent": 11.3, "avg_memory_percent": 17.8, "classification": "over-provisioned",  "estimated_monthly_savings_usd": 82.94},
        {"instance_id": "i-1b2c3d4e5f6a7890", "instance_type": "t3.large",   "name": "worker-node-1",    "avg_cpu_percent":  8.6, "avg_memory_percent": 14.2, "classification": "over-provisioned",  "estimated_monthly_savings_usd": 36.45},
        {"instance_id": "i-2c3d4e5f6a7b8901", "instance_type": "t3.medium",  "name": "cache-node",       "avg_cpu_percent": 43.5, "avg_memory_percent": 61.8, "classification": "right-sized",       "estimated_monthly_savings_usd":  0.0},
        {"instance_id": "i-3d4e5f6a7b8c9012", "instance_type": "c5.large",   "name": "batch-processor",  "avg_cpu_percent": 88.4, "avg_memory_percent": None, "classification": "under-provisioned", "estimated_monthly_savings_usd":  0.0},
        {"instance_id": "i-4e5f6a7b8c9d0123", "instance_type": "r5.large",   "name": "db-replica",       "avg_cpu_percent": 24.1, "avg_memory_percent": 73.6, "classification": "right-sized",       "estimated_monthly_savings_usd":  0.0},
    ]


_costs       = _build_costs()
_anomalies   = _build_anomalies()
_forecast    = _build_forecast()
_comparison  = _build_comparison()
_rightsizing = _build_rightsizing()


@app.get("/health")
def health():
    return {"status": "ok", "service": "costradar-mock-api"}

@app.get("/costs")
def costs():
    return _costs

@app.get("/anomalies")
def anomalies():
    return _anomalies

@app.get("/anomalies/comparison")
def comparison():
    return _comparison

@app.get("/forecast")
def forecast():
    return _forecast

@app.get("/rightsizing")
def rightsizing():
    return _rightsizing

@app.get("/alerts")
def alerts():
    return {
        "total_anomalies": len(_anomalies),
        "services_affected": list({a["service"] for a in _anomalies}),
        "latest_anomalies": _anomalies[:10],
    }

@app.post("/detect")
def detect():
    return {
        "cost_records_stored": len(_costs),
        "anomalies_detected": len(_anomalies),
        "alerts_sent": 3,
        "forecast_points": len(_forecast["points"]),
        "rightsizing_evaluated": len(_rightsizing),
    }


if __name__ == "__main__":
    print("\n  CostRadar mock API  →  http://localhost:8000")
    print("  Frontend            →  http://localhost:5173\n")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")
