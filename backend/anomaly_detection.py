"""
Two-model anomaly detection: Isolation Forest + Z-score baseline.

Running both independently matters because IF catches shape anomalies
in the distribution while Z-score catches raw magnitude spikes. Points
flagged by both are almost certainly real — flagged by only one warrant
a second look before acting on them.
"""

import logging
import uuid
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
from sklearn.ensemble import IsolationForest

from dynamo_client import DynamoClient

logger = logging.getLogger(__name__)

CONTAMINATION_RATE = 0.05
# 2.5σ is intentionally tight for cost data — billing spikes tend to be
# dramatic, so we only want to fire on genuinely unusual values
ZSCORE_THRESHOLD = 2.5


def _build_series(records: list[dict]) -> dict[str, list[dict]]:
    series: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        series[rec["service"]].append(rec)
    for svc in series:
        series[svc].sort(key=lambda r: r["date"])
    return dict(series)


def _zscore_analysis(costs: np.ndarray) -> tuple[list[float], list[bool]]:
    if len(costs) < 3 or np.std(costs) == 0:
        return [0.0] * len(costs), [False] * len(costs)
    mean = np.mean(costs)
    std = np.std(costs)
    z = ((costs - mean) / std).tolist()
    return z, [abs(v) > ZSCORE_THRESHOLD for v in z]


def _percentile(costs: np.ndarray, value: float) -> int:
    return int(np.searchsorted(np.sort(costs), value) / len(costs) * 100)


def _explain(
    cost: float,
    mean: float,
    std: float,
    z_score: float,
    percentile: int,
    if_flag: bool,
    z_flag: bool,
) -> str:
    direction = "above" if cost > mean else "below"
    sigma = f"{abs(z_score):.1f}σ {direction} the service mean (${mean:.2f})"
    rank = f"top {100 - percentile}%" if cost > mean else f"bottom {percentile}%"

    delta = abs(cost - mean)
    impact = (
        f"That's ${delta:.2f} {'more' if cost > mean else 'less'} than the typical daily spend for this service."
    )

    if if_flag and z_flag:
        confidence = "Both models flagged this — high confidence."
    elif if_flag:
        confidence = "Isolation Forest only — Z-score within normal range."
    else:
        confidence = "Z-score flagged — Isolation Forest considers it borderline."

    return f"${cost:.2f} sits {sigma}, placing it in the {rank} of recorded values. {impact} {confidence}"


def run_anomaly_detection(
    cost_records: list[dict], dynamo: DynamoClient | None = None
) -> list[dict]:
    if dynamo is None:
        dynamo = DynamoClient()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + f"_{uuid.uuid4().hex[:8]}"
    all_results: list[dict] = []

    for service, records in _build_series(cost_records).items():
        if len(records) < 3:
            logger.warning("Skipping %s — %d data points, need >= 3", service, len(records))
            continue

        costs = np.array([r["cost_usd"] for r in records])
        mean = float(np.mean(costs))
        std = float(np.std(costs))

        # Isolation Forest
        clf = IsolationForest(
            contamination=CONTAMINATION_RATE, random_state=42, n_estimators=100
        )
        clf.fit(costs.reshape(-1, 1))
        if_scores = (-clf.decision_function(costs.reshape(-1, 1))).tolist()
        if_flags = clf.predict(costs.reshape(-1, 1))

        # Z-score baseline runs independently — no shared state with IF
        z_scores, z_flags = _zscore_analysis(costs)

        for i, record in enumerate(records):
            cost = record["cost_usd"]
            if_flag = bool(if_flags[i] == -1)
            z_flag = bool(z_flags[i])
            pct = _percentile(costs, cost)

            result = {
                "run_id": run_id,
                "service": service,
                "date": record["date"],
                "cost_usd": cost,
                "anomaly_score": round(if_scores[i], 6),
                "is_anomaly": if_flag,
                "z_score": round(z_scores[i], 4),
                "z_score_flagged": z_flag,
                "consensus": if_flag and z_flag,
                "historical_mean": round(mean, 4),
                "historical_std": round(std, 4),
                "percentile": pct,
                "explanation": _explain(cost, mean, std, z_scores[i], pct, if_flag, z_flag),
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }
            all_results.append(result)
            dynamo.put_anomaly(run_id=run_id, record=result)

        if_count = sum(1 for r in all_results if r["service"] == service and r["is_anomaly"])
        z_count = sum(1 for r in all_results if r["service"] == service and r["z_score_flagged"])
        logger.info(
            "%s: %d records — IF=%d Z-score=%d consensus=%d",
            service, len(records), if_count, z_count,
            sum(1 for r in all_results if r["service"] == service and r["consensus"]),
        )

    return all_results


def filter_anomalies(results: list[dict]) -> list[dict]:
    """Flagged by either model; consensus items sorted first."""
    flagged = [r for r in results if r["is_anomaly"] or r["z_score_flagged"]]
    # stable two-pass sort: date descending, then confidence ascending
    flagged.sort(key=lambda r: r["date"], reverse=True)
    flagged.sort(key=lambda r: 0 if r["consensus"] else (1 if r["is_anomaly"] else 2))
    return flagged


def build_comparison_stats(results: list[dict]) -> dict:
    """Aggregate per-service IF vs Z-score detection counts for the comparison panel."""
    services: dict[str, dict] = {}
    for r in results:
        svc = r["service"]
        if svc not in services:
            services[svc] = {"service": svc, "if_count": 0, "z_count": 0, "consensus_count": 0, "total": 0}
        services[svc]["total"] += 1
        if r["is_anomaly"]:
            services[svc]["if_count"] += 1
        if r["z_score_flagged"]:
            services[svc]["z_count"] += 1
        if r["consensus"]:
            services[svc]["consensus_count"] += 1

    rows = list(services.values())
    total_if = sum(r["if_count"] for r in rows)
    total_z = sum(r["z_count"] for r in rows)
    total_consensus = sum(r["consensus_count"] for r in rows)
    agreement_rate = (
        round(total_consensus / max(total_if, total_z, 1) * 100, 1)
        if (total_if or total_z) else 0.0
    )

    return {
        "per_service": rows,
        "total_if": total_if,
        "total_z_score": total_z,
        "total_consensus": total_consensus,
        "agreement_rate_pct": agreement_rate,
    }
