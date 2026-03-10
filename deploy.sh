#!/usr/bin/env bash
set -euo pipefail

STACK_NAME="el-somer-brero"
REGION="${1:-mx-central-1}"
S3_BUCKET="${S3_BUCKET:-}"

echo "=== Deploying $STACK_NAME to $REGION ==="

# Build
sam build --region "$REGION"

# Deploy
DEPLOY_ARGS=(
  --stack-name "$STACK_NAME"
  --region "$REGION"
  --resolve-s3
  --capabilities CAPABILITY_IAM
  --no-confirm-changeset
  --no-fail-on-empty-changeset
)

if [[ -n "$S3_BUCKET" ]]; then
  DEPLOY_ARGS+=(--s3-bucket "$S3_BUCKET")
fi

sam deploy "${DEPLOY_ARGS[@]}"

# Get the API URL from stack outputs
FUNCTION_URL=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`ApiUrl`].OutputValue' \
  --output text)

echo ""
echo "=== Deployed! ==="
echo "Function URL: $FUNCTION_URL"
echo ""
echo "=== Invoking to check IP and country ==="
curl -s "$FUNCTION_URL" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin), indent=2, ensure_ascii=False))"
