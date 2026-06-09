# CostRadar — Complete Project Specification

This document describes everything built in CostRadar, exactly as it stands.
It covers the original requirements and every addition made beyond them.

---

## What the project does

CostRadar is an AWS spend anomaly detection and rightsizing intelligence platform.
It connects to real AWS Cost Explorer and CloudWatch APIs via boto3, runs two
independent anomaly detection models (Isolation Forest + Z-score baseline),
generates plain-English explanations for every flagged anomaly, forecasts 30-day
costs using Prophet with in-sample accuracy metrics, tracks spend against a
configurable monthly budget, recommends EC2 rightsizing based on actual CloudWatch
utilisation, and fires SNS alerts when anomaly scores breach a threshold. Everything
is served through a FastAPI backend and a React dashboard. A standalone mock server
allows full local development with no AWS credentials.

---

## Tech stack

- **Backend:** Python 3.11, FastAPI, boto3, scikit-learn (Isolation Forest),
  Prophet, pandas, numpy, python-dotenv, Mangum
- **Frontend:** React 18, Vite, Recharts, Tailwind CSS
- **AWS services:** Cost Explorer API, CloudWatch API, SNS, S3, DynamoDB,
  Lambda, EventBridge
- **Deployment:** AWS Lambda (backend via Mangum), S3 static hosting (frontend),
  DynamoDB (all persistence), EventBridge (scheduled detection)

---

## Complete feature list

### 1. Cost ingestion
Pull last 90 days of daily cost data per AWS service via Cost Explorer API.
Skip zero-cost lines. Store raw records in DynamoDB with date, service name,
cost value, and updated_at timestamp. Return records to the caller so the
detection pipeline can chain without a DynamoDB round-trip.

### 2. Dual-model anomaly detection *(original: Isolation Forest only)*
Run two independent models on each service's cost time series:

**Isolation Forest**
- contamination=0.05, n_estimators=100, random_state=42
- Scores are negated decision_function values — positive = more anomalous
- Services with fewer than 3 data points are skipped

**Z-score baseline** *(added beyond original spec)*
- Threshold: 2.5σ — intentionally tight to avoid alert fatigue
- Runs independently with no shared state with Isolation Forest

**Per-record output stored in DynamoDB:**
- `anomaly_score` — Isolation Forest score
- `is_anomaly` — Isolation Forest flag
- `z_score` — raw Z-score value
- `z_score_flagged` — Z-score flag
- `consensus` — True when both models agree (highest confidence)
- `historical_mean`, `historical_std`, `percentile`
- `explanation` — plain-English string (see below)
- `detected_at` timestamp

### 3. Anomaly explainability *(added beyond original spec)*
Every anomaly record includes a human-readable explanation built from the
model outputs:

Format:
> "$85.40 sits 4.2σ above the service mean ($18.20), placing it in the top 1%
> of recorded values. That's $67.20 more than the typical daily spend for this
> service. Both models flagged this — high confidence."

The explanation covers: σ deviation with direction, dollar impact above or below
typical spend, percentile rank, and which model(s) flagged it with a confidence
label (both models / Isolation Forest only / Z-score only).

### 4. Model comparison stats *(added beyond original spec)*
`build_comparison_stats()` aggregates per-service detection counts across both
models and computes an overall agreement rate. Returned from the
`/anomalies/comparison` endpoint and displayed in the Model Comparison panel.

Fields: `per_service` (list of per-service IF/Z-score/consensus counts),
`total_if`, `total_z_score`, `total_consensus`, `agreement_rate_pct`.

### 5. Forecasting with accuracy metrics *(original: forecast only)*
Run Prophet on aggregated daily total cost:
- `weekly_seasonality=True`, `daily_seasonality=False`
- 95% confidence interval, `uncertainty_samples=500`
- 30-day forward projection
- Negative lower bounds clamped to 0

**Accuracy metrics computed after every run** *(added beyond original spec)*:
- MAE (mean absolute error) — in-sample fit quality
- MAPE (mean absolute percentage error) — skips near-zero actuals
- R² (goodness of fit)
- `data_points_used` — training window size

**Budget projection** *(added beyond original spec)*:
If `MONTHLY_BUDGET_USD` is set, computes:
- `actual_month_to_date` — real spend so far this month
- `forecast_remaining` — Prophet forecast for remaining days in month
- `projected_month_total` — sum of above
- `overage_usd` — amount over budget (0 if under)
- `breach_day` — specific date cumulative spend crosses the budget line
- `status` — `under_budget` / `at_risk` (within 15%) / `over_budget`

All forecast points and metrics stored in DynamoDB. Metrics stored as a
special item with `sk=METRICS` alongside the forecast DATE# items.

### 6. EC2 rightsizing
For each running EC2 instance, pull 14-day average CPU and memory utilisation
from CloudWatch. Memory requires the CloudWatch agent (`CWAgent` namespace).

Classification thresholds (exactly as specified):
- CPU < 20% → over-provisioned
- CPU > 80% → under-provisioned
- Otherwise → right-sized

Memory acts as a tiebreaker: an instance is only over-provisioned if both CPU
and memory (when available) are below their thresholds.

Monthly savings estimated at 40% of the known On-Demand rate for the instance
type (conservative estimate). Pricing table covers t3, m5, c5, r5 families.

### 7. SNS alerting
When `is_anomaly=True` and `anomaly_score > ANOMALY_ALERT_THRESHOLD`, publish
a structured JSON message to the configured SNS topic containing: `source`,
`alert_type`, `service`, `date`, `cost_usd`, `anomaly_score`, `detected_at`.
MessageAttributes added for downstream filtering by service and alert type.
Suppressed silently if `SNS_TOPIC_ARN` is not set (local dev mode).

### 8. EventBridge scheduling
Rule `cron(0 8 * * ? *)` triggers the Lambda function daily at 08:00 UTC.
The Lambda handler detects EventBridge events by `source=aws.events` and
routes them to the scheduled pipeline. All other events route to Mangum/FastAPI.

### 9. REST API

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness probe |
| GET | `/costs` | All stored daily cost records, newest first |
| GET | `/anomalies` | Records flagged by either model, latest run |
| GET | `/anomalies/comparison` | Per-service IF vs Z-score counts + agreement rate |
| GET | `/forecast` | Forecast points + accuracy metrics + budget projection |
| GET | `/rightsizing` | EC2 recommendations sorted by savings descending |
| GET | `/alerts` | Anomaly alert summary |
| POST | `/detect` | Run full detection pipeline on demand |

`/forecast` returns a structured object, not a flat array:
```json
{
  "points": [...],
  "accuracy": { "mae": 1.84, "mape": 5.32, "r_squared": 0.91, "data_points_used": 90 },
  "budget": { "status": "at_risk", "projected_month_total": 431.20, "breach_day": "2026-06-28", ... }
}
```

### 10. Frontend dashboard

**CostTrendChart** — Recharts ComposedChart with gradient area fill under the
cost line. Red ReferenceDots mark anomaly dates. Anomaly count shown in footer.

**AnomalyTable** — every row is clickable and expands to show the plain-English
explanation, σ deviation, Z-score value, and percentile. Each row shows a model
badge (Both models / IF only / Z-score only). Consensus rows sorted first.
Header shows breakdown: X consensus · X IF · X Z-score.

**ModelComparisonPanel** *(added beyond original spec)* — grouped bar chart
(Recharts BarChart) showing per-service Isolation Forest, Z-score, and consensus
detection counts side by side. Summary stat chips show total counts and agreement
rate. A note explains that consensus = highest confidence, single-model = review.

**ForecastChart** — ComposedChart with confidence band rendered as two stacked
Area components. Vertical ReferenceLine marks today. Below the chart, four
MetricChip components display MAE, MAPE, R², and data points used.

**BudgetAlert** *(added beyond original spec)* — full-width card between KPI
strip and charts. Shows a progress bar of projected month-end spend vs budget,
colour-coded green/amber/red. Displays: spent so far, forecast remaining,
projected overage, and breach day. Hidden when `MONTHLY_BUDGET_USD` is 0.

**RightsizingTable** — instance ID, type, CPU bar, memory bar, classification
badge, and savings/month. Summary strip at bottom: over-provisioned count,
total instances, potential monthly savings.

**KPI strip** — 90-day spend, anomalies flagged (with consensus count as sub-
label), forecast horizon (with MAPE as sub-label when available), estimated
monthly savings.

### 11. Mock server *(added beyond original spec)*
`backend/mock_server.py` — standalone FastAPI app on port 8000. No AWS
credentials or DynamoDB tables required. Serves realistic fake data for all
endpoints including the new explainability fields, model comparison stats,
forecast accuracy metrics, and budget projection. Data is deterministic
(seeded RNG) and date-relative (offsets from today). Intended for local
development and Hugging Face demo deployment.

### 12. SVG logo and favicon *(added beyond original spec)*
`frontend/public/logo.svg` — two concentric radar rings in indigo with an
ascending polyline and endpoint dot. Used as the browser favicon via
`<link rel="icon" type="image/svg+xml" href="/logo.svg">` and inlined as
a React component in the header.

---

## Project structure (as built)

```
costradar/
├── backend/
│   ├── main.py                FastAPI app, response models, all endpoints
│   ├── cost_ingestion.py      Cost Explorer → DynamoDB, daily totals
│   ├── anomaly_detection.py   IF + Z-score, explainability, comparison stats
│   ├── forecasting.py         Prophet, MAE/MAPE/R², budget projection
│   ├── rightsizing.py         CloudWatch EC2, savings estimates
│   ├── alerting.py            SNS alerts with MessageAttributes
│   ├── dynamo_client.py       DynamoDB wrapper, forecast metrics storage
│   ├── mock_server.py         Standalone dev server, no AWS needed
│   ├── requirements.txt       Pinned versions
│   └── .env.example           All variables documented
├── frontend/
│   ├── public/
│   │   └── logo.svg           SVG favicon and header logo
│   ├── src/
│   │   ├── App.jsx            Root layout, data fetching, KPI strip
│   │   ├── main.jsx           React DOM entry point
│   │   ├── index.css          Tailwind base styles, dark theme
│   │   └── components/
│   │       ├── CostTrendChart.jsx       Line + area chart with anomaly dots
│   │       ├── AnomalyTable.jsx         Expandable rows, model badges
│   │       ├── ModelComparisonPanel.jsx Grouped bar chart IF vs Z-score
│   │       ├── ForecastChart.jsx        Prophet chart + MAE/MAPE chips
│   │       ├── BudgetAlert.jsx          Budget status card
│   │       └── RightsizingTable.jsx     EC2 recommendations
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   └── postcss.config.js
├── infrastructure/
│   ├── lambda_handler.py      EventBridge + Mangum dual-mode handler
│   └── eventbridge_rule.json  Rule config + IAM snippets
├── .gitignore
└── README.md
```

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `AWS_REGION` | Yes | — | Region for all services |
| `AWS_ACCESS_KEY_ID` | Local only | — | Leave blank on Lambda |
| `AWS_SECRET_ACCESS_KEY` | Local only | — | Leave blank on Lambda |
| `DYNAMODB_COSTS_TABLE` | Yes | — | `costradar-costs` |
| `DYNAMODB_ANOMALIES_TABLE` | Yes | — | `costradar-anomalies` |
| `DYNAMODB_FORECAST_TABLE` | Yes | — | `costradar-forecast` |
| `DYNAMODB_RIGHTSIZING_TABLE` | Yes | — | `costradar-rightsizing` |
| `SNS_TOPIC_ARN` | No | — | Leave blank to suppress alerts |
| `ANOMALY_ALERT_THRESHOLD` | No | `0.1` | Min IF score to fire SNS |
| `MONTHLY_BUDGET_USD` | No | `0` | Set to 0 to disable budget tracking |
| `CORS_ORIGINS` | Yes | — | Comma-separated allowed origins |

---

## Code quality standards applied throughout

- No placeholders, no TODOs, no stub functions anywhere
- Comments explain why, never what — short and specific
- Descriptive, consistent variable names across all files
- Every AWS API call wrapped in `try/except ClientError` with the specific
  error code logged before re-raising
- DynamoDB float→Decimal conversion handled centrally in `dynamo_client.py`
- DynamoDB pagination handled on every scan (1 MB page limit)
- Prophet's verbose Stan output suppressed to keep Lambda logs clean
- Forecasting and rightsizing failures are non-fatal in the detection pipeline
  — the pipeline continues and returns partial results rather than returning 500
