# CostRadar

AWS spend anomaly detection and rightsizing intelligence platform. Pulls live billing data from Cost Explorer and CloudWatch, runs two independent anomaly detection models, forecasts 30-day costs with accuracy metrics, tracks spend against a monthly budget, and recommends EC2 rightsizing — all served through a FastAPI backend and a React dashboard.

Built by [SKMMT](http://skmmt.rootexception.com/)

---

## What it does

| Feature | Detail |
|---|---|
| **Cost ingestion** | Pulls 90 days of daily spend per AWS service via Cost Explorer |
| **Dual-model anomaly detection** | Isolation Forest + Z-score baseline run independently; consensus detections (flagged by both) are highest confidence |
| **Anomaly explainability** | Every flagged record shows the σ deviation, dollar impact above typical spend, percentile rank, and which model(s) flagged it |
| **Model comparison** | Grouped bar chart showing per-service IF vs Z-score detection counts and agreement rate |
| **30-day forecast** | Prophet model with weekly seasonality and 95% confidence interval |
| **Forecast accuracy** | In-sample MAE, MAPE, and R² displayed alongside the forecast chart |
| **Budget tracking** | Projected month-end spend vs configurable budget; breach day calculated from the forecast |
| **EC2 rightsizing** | 14-day CloudWatch CPU/memory averages classify each instance and estimate monthly savings |
| **SNS alerting** | Structured JSON alert published per anomaly when score exceeds threshold |
| **Scheduled detection** | EventBridge triggers the full pipeline daily at 08:00 UTC |

---

## Architecture

```
                          ┌─────────────────────────────────────────────┐
                          │                  AWS Account                │
                          │                                             │
  ┌─────────┐  REST API   │  ┌──────────────────────────────────────┐  │
  │  React  │◄────────────┤  │       Lambda Function URL            │  │
  │Dashboard│             │  └─────────────────┬────────────────────┘  │
  └─────────┘             │                    │                        │
       │                  │  ┌─────────────────▼────────────────────┐  │
       │ S3 static host   │  │      Lambda (Mangum + FastAPI)        │  │
       │                  │  │                                       │  │
  ┌────▼────┐             │  │  cost_ingestion  →  DynamoDB         │  │
  │   S3    │             │  │  anomaly_detection (IF + Z-score)    │  │
  │ (dist/) │             │  │  forecasting     (Prophet + metrics) │  │
  └─────────┘             │  │  rightsizing     →  CloudWatch       │  │
                          │  │  alerting        →  SNS              │  │
                          │  └──────────────────────────────────────┘  │
                          │                                             │
                          │  EventBridge  cron(0 8 * * ? *)            │
                          │      └──► Lambda (daily pipeline)          │
                          └─────────────────────────────────────────────┘
```

---

## Project Structure

```
costradar/
├── backend/
│   ├── main.py                FastAPI app — all REST endpoints + response models
│   ├── cost_ingestion.py      Cost Explorer → DynamoDB, daily totals aggregation
│   ├── anomaly_detection.py   Isolation Forest + Z-score, explainability, comparison stats
│   ├── forecasting.py         Prophet forecast, MAE/MAPE/R², budget projection
│   ├── rightsizing.py         CloudWatch EC2 evaluation, savings estimates
│   ├── alerting.py            SNS anomaly alerts with score threshold
│   ├── dynamo_client.py       DynamoDB read/write wrapper, forecast metrics storage
│   ├── mock_server.py         Standalone dev server — no AWS credentials needed
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.jsx                      Root layout, data fetching, KPI strip
│   │   ├── main.jsx
│   │   ├── index.css
│   │   └── components/
│   │       ├── CostTrendChart.jsx        Line chart with anomaly markers
│   │       ├── AnomalyTable.jsx          Expandable rows with explanations + model badges
│   │       ├── ModelComparisonPanel.jsx  IF vs Z-score grouped bar chart
│   │       ├── ForecastChart.jsx         30-day projection + MAE/MAPE chips
│   │       ├── BudgetAlert.jsx           Projected spend vs monthly budget
│   │       └── RightsizingTable.jsx      EC2 recommendations with savings
│   ├── public/
│   │   └── logo.svg
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   └── postcss.config.js
├── infrastructure/
│   ├── lambda_handler.py      EventBridge + Mangum dual-mode handler
│   └── eventbridge_rule.json  EventBridge rule + IAM snippets
└── README.md
```

---

## Prerequisites

- Python 3.11 (not 3.12+ — Prophet and scikit-learn wheels require 3.11)
- Node.js 18+
- AWS account with Cost Explorer enabled
- AWS CLI configured (`aws configure`)

### Required IAM Permissions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ce:GetCostAndUsage",
        "ec2:DescribeInstances",
        "cloudwatch:GetMetricStatistics",
        "dynamodb:PutItem",
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "sns:Publish",
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## Local Development

### 1. Backend

```powershell
cd backend
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
# Fill in AWS credentials and table names
```

### 2. Run without AWS (mock server)

No credentials or DynamoDB tables needed. Serves realistic fake data including anomaly explanations, model comparison, forecast metrics, and budget projection.

```powershell
python mock_server.py
```

### 3. Run with real AWS data

Enable Cost Explorer in the AWS console, create the four DynamoDB tables, fill in `.env`, then:

```powershell
uvicorn main:app --reload --port 8000
```

Create DynamoDB tables (one-time):

```bash
for table in costradar-costs costradar-anomalies costradar-forecast costradar-rightsizing; do
  aws dynamodb create-table \
    --table-name $table \
    --attribute-definitions AttributeName=pk,AttributeType=S AttributeName=sk,AttributeType=S \
    --key-schema AttributeName=pk,KeyType=HASH AttributeName=sk,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST
done
```

### 4. Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. The Vite dev proxy forwards `/api/*` to port 8000.

### 5. Trigger detection

Click **Run Detection** in the dashboard, or:

```bash
curl -X POST http://localhost:8000/detect
```

---

## Production Deployment

### Backend → Lambda

Prophet and scikit-learn contain compiled C extensions that must be built for Amazon Linux. Use Docker:

```bash
cd backend
docker run --rm \
  -v "${PWD}:/var/task" \
  public.ecr.aws/lambda/python:3.11 \
  pip install -r requirements.txt -t ./package/ --quiet

cp *.py package/
cp ../infrastructure/lambda_handler.py package/
cd package && zip -r ../costradar-backend.zip . && cd ..

aws lambda create-function \
  --function-name costradar-backend \
  --runtime python3.11 \
  --role arn:aws:iam::ACCOUNT_ID:role/costradar-lambda-role \
  --handler lambda_handler.handler \
  --zip-file fileb://costradar-backend.zip \
  --timeout 300 \
  --memory-size 1024

aws lambda create-function-url-config \
  --function-name costradar-backend \
  --auth-type NONE \
  --cors AllowOrigins="*"
```

Set environment variables on the Lambda function (Configuration → Environment variables):
all variables from `.env`, plus `MONTHLY_BUDGET_USD`.

### Frontend → S3

```bash
cd frontend
VITE_API_URL=https://your-lambda-url.lambda-url.eu-west-2.on.aws npm run build
aws s3 sync dist/ s3://your-bucket/ --delete --acl public-read
```

### EventBridge schedule

```bash
aws events put-rule \
  --name costradar-daily \
  --schedule-expression "cron(0 8 * * ? *)" \
  --state ENABLED \
  --region eu-west-2

aws events put-targets \
  --rule costradar-daily \
  --targets "Id=lambda,Arn=arn:aws:lambda:eu-west-2:ACCOUNT_ID:function:costradar-backend" \
  --region eu-west-2

aws lambda add-permission \
  --function-name costradar-backend \
  --statement-id allow-eventbridge \
  --action lambda:InvokeFunction \
  --principal events.amazonaws.com \
  --source-arn arn:aws:events:eu-west-2:ACCOUNT_ID:rule/costradar-daily
```

---

## API Reference

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness probe |
| GET | `/costs` | All stored daily cost records |
| GET | `/anomalies` | Flagged records from latest run (IF + Z-score fields included) |
| GET | `/anomalies/comparison` | Per-service IF vs Z-score detection counts and agreement rate |
| GET | `/forecast` | Forecast points + accuracy metrics + budget projection |
| GET | `/rightsizing` | EC2 rightsizing recommendations |
| GET | `/alerts` | Anomaly alert summary |
| POST | `/detect` | Run full detection pipeline immediately |

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `AWS_REGION` | Yes | AWS region for all services (e.g. `eu-west-2`) |
| `AWS_ACCESS_KEY_ID` | Local only | Leave blank on Lambda — uses execution role |
| `AWS_SECRET_ACCESS_KEY` | Local only | Leave blank on Lambda |
| `DYNAMODB_COSTS_TABLE` | Yes | `costradar-costs` |
| `DYNAMODB_ANOMALIES_TABLE` | Yes | `costradar-anomalies` |
| `DYNAMODB_FORECAST_TABLE` | Yes | `costradar-forecast` |
| `DYNAMODB_RIGHTSIZING_TABLE` | Yes | `costradar-rightsizing` |
| `SNS_TOPIC_ARN` | No | Leave blank to disable alerts |
| `ANOMALY_ALERT_THRESHOLD` | No | Default `0.1` |
| `MONTHLY_BUDGET_USD` | No | Set to `0` to disable budget tracking |
| `CORS_ORIGINS` | Yes | Comma-separated allowed origins |

---

## AWS Cost Estimate

| Service | Usage | Monthly cost |
|---|---|---|
| Cost Explorer API | 1 call/day | ~$0.31 |
| DynamoDB | On-demand, small dataset | ~$0.00 |
| Lambda | 1 invocation/day | ~$0.00 |
| CloudWatch | Read-only metric queries | ~$0.00 |
| SNS | Per anomaly detected | ~$0.00 |
| S3 | Static frontend assets | ~$0.00 |
| EventBridge | 1 scheduled event/day | ~$0.00 |

Cost Explorer is the only billable service at normal usage. Total: **~$0.31/month**, fully covered by AWS Free Tier credits on new accounts.
