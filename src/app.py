import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

import boto3

# Initialised lazily in _write_access_log so module import never calls boto3
# without a region (which would crash the test collector in CI).
_dynamodb = None


def lambda_handler(event, context):
    started_at = time.perf_counter()
    request_context = event.get("requestContext", {})
    identity = request_context.get("identity", {})

    # Get public IP
    ip = _get_public_ip()

    # Geolocate it
    geo = _geolocate(ip)
    if "_error" in geo:
        print(f"[GEO_FAILURE] target=lambda ip={ip} error={geo['_error']}")

    source_ip = identity.get("sourceIp", "unknown")
    source_geo = _geolocate(source_ip) if source_ip != "unknown" else {}
    if "_error" in source_geo:
        err = source_geo["_error"]
        print(f"[GEO_FAILURE] target=caller ip={source_ip} error={err}")

    # Snap time after all external calls (ipify + both ipapi lookups).
    duration_ms = round((time.perf_counter() - started_at) * 1000, 2)

    request_record = {
        "request_id": getattr(context, "aws_request_id", "unknown"),
        "invoked_at": datetime.now(timezone.utc).isoformat(),
        "api_request_id": request_context.get("requestId", "unknown"),
        "api_stage": request_context.get("stage", "unknown"),
        "http_method": event.get("httpMethod", "unknown"),
        "path": event.get("path", "unknown"),
        "source_ip": source_ip,
        "caller_country": source_geo.get("country_name", "unknown"),
        "caller_country_code": source_geo.get("country_code", "unknown"),
        "caller_city": source_geo.get("city", "unknown"),
        "user_agent": identity.get("userAgent", "unknown"),
        "observed_public_ip": ip,
        "lambda_country": geo.get("country_name", "unknown"),
        "lambda_country_code": geo.get("country_code", "unknown"),
        "lambda_region": geo.get("region", "unknown"),
        "lambda_city": geo.get("city", "unknown"),
        "lambda_org": geo.get("org", "unknown"),
        "response_time_ms": Decimal(str(duration_ms)),
        # Unix epoch timestamp used by DynamoDB TTL to expire this item.
        "expires_at": int(time.time()) + 365 * 24 * 60 * 60,
    }

    # Store the raw error reason when a geo lookup failed so it is
    # queryable in DynamoDB alongside the 'unknown' country fields.
    if "_error" in geo:
        request_record["lambda_geo_error"] = geo["_error"]
    if "_error" in source_geo:
        request_record["caller_geo_error"] = source_geo["_error"]

    _write_access_log(request_record)

    result = {
        "lambda_public_ip": ip,
        "lambda_country": geo.get("country_name", "unknown"),
        "lambda_country_code": geo.get("country_code", "unknown"),
        "lambda_city": geo.get("city", "unknown"),
        "caller_ip": source_ip,
        "caller_country": source_geo.get("country_name", "unknown"),
        "caller_country_code": source_geo.get("country_code", "unknown"),
        "caller_city": source_geo.get("city", "unknown"),
        "response_time_ms": duration_ms,
    }

    return {
        "statusCode": 200,
        "body": json.dumps(result, indent=2),
        "headers": {"Content-Type": "application/json"},
    }


def _get_public_ip():
    try:
        url = "https://api.ipify.org?format=json"
        with urllib.request.urlopen(url, timeout=5) as r:
            return json.loads(r.read())["ip"]
    except (urllib.error.URLError, KeyError):
        return "unknown"


def _geolocate(ip):
    url = f"https://ipapi.co/{ip}/json/"
    req = urllib.request.Request(url, headers={"User-Agent": "el-somer-brero-poc/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as exc:
        # ipapi.co free tier rate-limits at ~30 req/min; return a partial result.
        return {"_error": f"geo_lookup_failed:{exc.code}"}
    except urllib.error.URLError:
        return {"_error": "geo_lookup_failed:network_error"}


def _write_access_log(item):
    global _dynamodb
    table_name = os.environ.get("ACCESS_LOG_TABLE")
    if not table_name:
        return
    if _dynamodb is None:
        _dynamodb = boto3.resource("dynamodb")
    try:
        table = _dynamodb.Table(table_name)
        table.put_item(Item=item)
    except Exception as exc:
        # Log and swallow so a DynamoDB failure never surfaces as a 502.
        print(f"[WARN] access log write failed: {exc}")
