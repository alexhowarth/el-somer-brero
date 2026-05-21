# el-somer-brero 🇲🇽

Proof of concept: deploy an AWS Lambda to the Mexico (`mx-central-1`) region and verify it gets a Mexican IP address via geolocation lookup.

## Prerequisites

- AWS CLI configured with valid credentials
- AWS SAM CLI installed
- Python 3.12
- **Mexico (Central) region enabled** — go to **AWS Console → Account → Regions** and opt in to `mx-central-1` if not already enabled

## Deploy

```bash
./deploy.sh            # defaults to mx-central-1
```

### Example output

```
=== Deploying el-somer-brero to mx-central-1 ===
...
Successfully created/updated stack - el-somer-brero in mx-central-1

=== Deployed! ===
API URL: https://xfi4b8lil0.execute-api.mx-central-1.amazonaws.com/tacos/

=== Invoking to check IP and country ===
{
  "lambda_public_ip": "78.13.106.33",
  "lambda_country": "Mexico",
  "lambda_country_code": "MX",
  "lambda_city": "Querétaro City",
  "caller_ip": "72.68.68.47",
  "caller_country": "United States",
  "caller_country_code": "US",
  "caller_city": "New York City",
  "response_time_ms": 834.21
}
```

Geo fields show `"unknown"` if ipapi.co's free tier rate limit (~30 req/min) is hit; the `[GEO_FAILURE]` CloudWatch metric and alarm will fire in that case.

## Local development

```bash
pip install -r requirements-dev.txt
python -m pytest tests/                         # run tests
ruff check src/ tests/ && ruff format --check src/ tests/   # lint
sam validate --lint --region mx-central-1       # validate template
```

## CI

GitHub Actions runs three parallel jobs on every push and PR to `main`:

| Job | What it does |
|---|---|
| `lint` | `ruff check` + `ruff format --check` |
| `test` | `pytest` with 80% coverage threshold |
| `sam-validate` | `sam validate --lint` against mx-central-1 |

## Observability

Every invocation writes a record to a DynamoDB access log table (1-year TTL, retained on stack deletion). A CloudWatch dashboard (`el-somer-brero-observability`) tracks Lambda duration, invocations/errors, API Gateway latency, DynamoDB writes, and geo lookup failures. An alarm fires if any geo lookup fails in a 5-minute window.

## Cleanup

```bash
aws cloudformation delete-stack --stack-name el-somer-brero --region mx-central-1
```

> The DynamoDB access log table has `DeletionPolicy: Retain` — it will survive the stack deletion and must be removed manually if no longer needed.

## Costs

Lambda pricing is consistent globally at $0.20 per 1M requests after the free tier.

| Component | Rate | This Lambda (128MB, ~1s) |
|---|---|---|
| Requests | $0.20 / 1M | $0.0000002 per call |
| Compute | $0.0000166667 / GB-s | ~$0.0000021 per call |
| API Gateway | $1.00 / 1M | $0.000001 per call |
| **Total per call** | | **~$0.0000033** |
| **1M calls/month** | | **~$3.50** |

The free tier includes 1M Lambda requests and 400,000 GB-seconds of compute per month — enough 
to cover ~3.1M invocations at this configuration.
