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
