"""
Unit tests for src/app.py.

Strategy
--------
app.py calls external services (ipify, ipapi.co) and DynamoDB, so every test
that touches lambda_handler patches those dependencies away.  No real network
calls or AWS credentials are needed.

Key patching targets
--------------------
- app._get_public_ip          - hides the ipify HTTP call
- app._geolocate              - hides the ipapi.co HTTP call
- app._write_access_log       - hides the DynamoDB write (used in handler tests)
- app._dynamodb               - the module-level boto3 resource object
- urllib.request.urlopen      - used when testing _geolocate's own internals
"""

import json
import os
import urllib.error
from unittest.mock import MagicMock, patch

import pytest  # noqa: F401 – imported so pytest picks up this file cleanly

from app import _geolocate, _write_access_log, lambda_handler

# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

# Realistic geo responses for the two IPs we use in most tests.
_GEO_LAMBDA = {
    "country_name": "Mexico",
    "country_code": "MX",
    "city": "Querétaro",
    "region": "QRO",
    "org": "AS16509 Amazon.com",
}

_GEO_CALLER = {
    "country_name": "Spain",
    "country_code": "ES",
    "city": "Madrid",
    "region": "MD",
    "org": "AS3352 Telefonica",
}


def _make_event(source_ip: str = "5.6.7.8") -> dict:
    """Build a minimal API Gateway proxy event."""
    return {
        "requestContext": {
            "identity": {"sourceIp": source_ip, "userAgent": "pytest"},
            "requestId": "apigw-req-id",
            "stage": "tacos",
        },
        "httpMethod": "GET",
        "path": "/",
    }


def _make_context() -> MagicMock:
    """Return a mock Lambda context with a predictable request ID."""
    ctx = MagicMock()
    ctx.aws_request_id = "lambda-req-id"
    return ctx


# ---------------------------------------------------------------------------
# Test 1 — Happy-path response shape
#
# Verifies that the handler returns a well-formed API Gateway response:
# correct status code, Content-Type header, and all expected body keys.
# ---------------------------------------------------------------------------


@patch("app._write_access_log")  # prevent DynamoDB write
@patch("app._geolocate")  # prevent ipapi.co call
@patch("app._get_public_ip")  # prevent ipify call
def test_lambda_handler_response_shape(mock_get_ip, mock_geolocate, mock_write_log):
    mock_get_ip.return_value = "1.2.3.4"
    # _geolocate is called twice: once for the Lambda's own IP, once for the
    # caller's IP.  side_effect lets us return different values per call.
    mock_geolocate.side_effect = [_GEO_LAMBDA, _GEO_CALLER]

    response = lambda_handler(_make_event(), _make_context())

    assert response["statusCode"] == 200
    assert response["headers"]["Content-Type"] == "application/json"

    body = json.loads(response["body"])
    expected_keys = {
        "lambda_public_ip",
        "lambda_country",
        "lambda_country_code",
        "lambda_city",
        "caller_ip",
        "caller_country",
        "caller_country_code",
        "caller_city",
        "response_time_ms",
    }
    assert expected_keys.issubset(body.keys()), (
        f"Missing keys: {expected_keys - body.keys()}"
    )
    assert body["lambda_public_ip"] == "1.2.3.4"
    assert body["lambda_country"] == "Mexico"
    assert body["caller_ip"] == "5.6.7.8"
    assert body["caller_country"] == "Spain"


# ---------------------------------------------------------------------------
# Test 2 — Response body is valid JSON (Decimal is not serialised into body)
#
# app.py stores response_time_ms as a Decimal in DynamoDB but must return it
# as a plain float in the HTTP response.  json.dumps raises TypeError if a
# Decimal leaks into the response dict — this test catches that regression.
# ---------------------------------------------------------------------------


@patch("app._write_access_log")
@patch("app._geolocate")
@patch("app._get_public_ip")
def test_response_body_is_valid_json_no_decimal(
    mock_get_ip, mock_geolocate, mock_write_log
):
    mock_get_ip.return_value = "1.2.3.4"
    mock_geolocate.side_effect = [_GEO_LAMBDA, _GEO_CALLER]

    response = lambda_handler(_make_event(), _make_context())

    # json.loads raises ValueError/TypeError if the body is not valid JSON.
    body = json.loads(response["body"])
    # response_time_ms must arrive as a float, not a Decimal.
    assert isinstance(body["response_time_ms"], float)


# ---------------------------------------------------------------------------
# Test 3 — _geolocate handles HTTP 429 rate-limit gracefully
#
# ipapi.co's free tier rate-limits at ~30 req/min.  The function should never
# raise; instead it returns a dict with an "_error" key so callers can still
# build a partial response.
# ---------------------------------------------------------------------------


def test_geolocate_rate_limit_returns_error_dict():
    # Simulate ipapi.co responding with HTTP 429 Too Many Requests.
    http_429 = urllib.error.HTTPError(
        url="https://ipapi.co/1.2.3.4/json/",
        code=429,
        msg="Too Many Requests",
        hdrs=None,
        fp=None,
    )
    with patch("urllib.request.urlopen", side_effect=http_429):
        result = _geolocate("1.2.3.4")

    assert "_error" in result, "Expected '_error' key when geo lookup fails"
    assert result["_error"] == "geo_lookup_failed:429"


# ---------------------------------------------------------------------------
# Test 4 — _write_access_log is a no-op when ACCESS_LOG_TABLE is not set
#
# The env var is optional so the function can be invoked (e.g. locally) without
# a real DynamoDB table.  This test verifies boto3 is never touched in that
# case, which also prevents accidental writes during local development.
# ---------------------------------------------------------------------------


def test_write_access_log_skips_without_env_var():
    with patch("app._dynamodb") as mock_dynamodb:
        # Build an environment that definitely does not contain ACCESS_LOG_TABLE.
        env_without_table = {
            k: v for k, v in os.environ.items() if k != "ACCESS_LOG_TABLE"
        }
        with patch.dict(os.environ, env_without_table, clear=True):
            _write_access_log({"request_id": "x", "invoked_at": "now"})

        # DynamoDB must not have been touched.
        mock_dynamodb.Table.assert_not_called()


# ---------------------------------------------------------------------------
# Test 5 — _write_access_log calls put_item with the correct item
#
# When the env var IS set, the function must look up the right table and write
# the item exactly as received — no fields dropped or mutated.
# ---------------------------------------------------------------------------


def test_write_access_log_calls_put_item_with_correct_item():
    item = {"request_id": "abc-123", "invoked_at": "2026-05-21T00:00:00+00:00"}
    mock_table = MagicMock()

    with patch("app._dynamodb") as mock_dynamodb:
        mock_dynamodb.Table.return_value = mock_table
        with patch.dict(os.environ, {"ACCESS_LOG_TABLE": "my-access-log-table"}):
            _write_access_log(item)

    # Correct table name must be resolved from the env var.
    mock_dynamodb.Table.assert_called_once_with("my-access-log-table")
    # The item must be written exactly as passed in — no mutations.
    mock_table.put_item.assert_called_once_with(Item=item)


# ---------------------------------------------------------------------------
# Test 6 — source_ip == "unknown" skips the caller geo lookup
#
# API Gateway populates sourceIp when the caller is known.  If it is absent
# the handler substitutes "unknown" and must NOT call _geolocate for it
# (which would produce a nonsensical lookup for the literal string "unknown").
# ---------------------------------------------------------------------------


@patch("app._write_access_log")
@patch("app._geolocate")
@patch("app._get_public_ip")
def test_unknown_source_ip_skips_caller_geo_lookup(
    mock_get_ip, mock_geolocate, mock_write_log
):
    mock_get_ip.return_value = "1.2.3.4"
    # Only one geolocate call should occur — for the Lambda's own IP.
    mock_geolocate.return_value = _GEO_LAMBDA

    response = lambda_handler(_make_event(source_ip="unknown"), _make_context())

    assert mock_geolocate.call_count == 1, (
        "_geolocate should only be called once (for Lambda IP), not for 'unknown'"
    )
    body = json.loads(response["body"])
    assert body["caller_ip"] == "unknown"
    assert body["caller_country"] == "unknown"


# ---------------------------------------------------------------------------
# Test 7 — _get_public_ip returns "unknown" on network failure
#
# ipify.org being unreachable should not crash the Lambda; the handler must
# still return a 200 with "unknown" for the IP-derived fields.
# ---------------------------------------------------------------------------


def test_get_public_ip_returns_unknown_on_network_error():
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        from app import _get_public_ip

        result = _get_public_ip()
    assert result == "unknown"


# ---------------------------------------------------------------------------
# Test 8 — _geolocate returns error dict on generic network failure (URLError)
#
# Covers the second except branch added for non-HTTP errors such as timeouts
# and DNS failures, which are not HTTPError instances.
# ---------------------------------------------------------------------------


def test_geolocate_network_error_returns_error_dict():
    network_err = urllib.error.URLError("timed out")
    with patch("urllib.request.urlopen", side_effect=network_err):
        result = _geolocate("1.2.3.4")
    assert result == {"_error": "geo_lookup_failed:network_error"}


# ---------------------------------------------------------------------------
# Test 9 — _write_access_log swallows DynamoDB exceptions
#
# A boto3/DynamoDB failure must be logged and swallowed so it never causes the
# Lambda to return a 502 to the caller.
# ---------------------------------------------------------------------------


def test_write_access_log_swallows_dynamodb_exception(capsys):
    mock_table = MagicMock()
    mock_table.put_item.side_effect = RuntimeError("DynamoDB unavailable")

    with patch("app._dynamodb") as mock_dynamodb:
        mock_dynamodb.Table.return_value = mock_table
        with patch.dict(os.environ, {"ACCESS_LOG_TABLE": "my-table"}):
            # Should not raise.
            _write_access_log({"request_id": "x", "invoked_at": "now"})

    captured = capsys.readouterr()
    assert "[WARN]" in captured.out


# ---------------------------------------------------------------------------
# Test 10 — geo failure is logged to stdout and stored in DynamoDB record
#
# When ipapi.co returns an error for the Lambda's own IP, the handler must:
#   a) print a [GEO_FAILURE] line so CloudWatch Logs (and the metric filter)
#      can pick it up, and
#   b) write lambda_geo_error into the DynamoDB record so the reason is
#      queryable later alongside the 'unknown' country fields.
# ---------------------------------------------------------------------------


@patch("app._write_access_log")
@patch("app._geolocate")
@patch("app._get_public_ip")
def test_geo_failure_logged_and_stored_in_record(
    mock_get_ip, mock_geolocate, mock_write_log, capsys
):
    mock_get_ip.return_value = "1.2.3.4"
    # Lambda IP lookup fails; caller lookup succeeds.
    mock_geolocate.side_effect = [
        {"_error": "geo_lookup_failed:429"},
        _GEO_CALLER,
    ]

    lambda_handler(_make_event(), _make_context())

    # a) A [GEO_FAILURE] line must appear in stdout (picked up by CloudWatch).
    captured = capsys.readouterr()
    assert "[GEO_FAILURE]" in captured.out
    assert "geo_lookup_failed:429" in captured.out

    # b) The error reason must be in the record passed to _write_access_log.
    record = mock_write_log.call_args[0][0]
    assert record.get("lambda_geo_error") == "geo_lookup_failed:429"
    # Caller lookup succeeded so no caller_geo_error field.
    assert "caller_geo_error" not in record


# ---------------------------------------------------------------------------
# Test 11 — caller geo failure is also logged and stored
#
# Same as test 10 but for the caller IP geo lookup failing instead.
# ---------------------------------------------------------------------------


@patch("app._write_access_log")
@patch("app._geolocate")
@patch("app._get_public_ip")
def test_caller_geo_failure_logged_and_stored(
    mock_get_ip, mock_geolocate, mock_write_log, capsys
):
    mock_get_ip.return_value = "1.2.3.4"
    # Lambda IP lookup succeeds; caller lookup fails.
    mock_geolocate.side_effect = [
        _GEO_LAMBDA,
        {"_error": "geo_lookup_failed:429"},
    ]

    lambda_handler(_make_event(), _make_context())

    captured = capsys.readouterr()
    assert "[GEO_FAILURE]" in captured.out

    record = mock_write_log.call_args[0][0]
    assert record.get("caller_geo_error") == "geo_lookup_failed:429"
    assert "lambda_geo_error" not in record
