# el-somer-brero 🇲🇽

Proof of concept: deploy an AWS Lambda to the Mexico (`mx-central-1`) region and verify it gets a Mexican IP address via geolocation lookup.

## Prerequisites

- AWS CLI configured with valid credentials
- AWS SAM CLI installed
- **Mexico (Central) region enabled** — go to **AWS Console → Account → Regions** and opt in to `mx-central-1` if not already enabled

## Deploy

```bash
./deploy.sh            # defaults to mx-central-1
```

### Example output

```
=== Deploying el-somer-brero to mx-central-1 ===
Building codeuri: /Users/alex/src/el-somer-brero/src runtime: python3.12 architecture: x86_64 functions:
IpLookupFunction

Build Succeeded

Successfully created/updated stack - el-somer-brero in mx-central-1

=== Deployed! ===
Function URL: https://xfi4b8lil0.execute-api.mx-central-1.amazonaws.com/tacos/

=== Invoking to check IP and country ===
{
  "public_ip": "78.13.106.33",
  "country": "Mexico",
  "country_code": "MX",
  "region": "Querétaro",
  "city": "Querétaro City",
  "org": "Amazon.com, Inc."
}
```

## Cleanup

```bash
aws cloudformation delete-stack --stack-name el-somer-brero --region mx-central-1
```

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
