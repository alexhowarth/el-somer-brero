import json
import urllib.request


def lambda_handler(event, context):
    # Get public IP
    ip = _get_public_ip()

    # Geolocate it
    geo = _geolocate(ip)

    result = {
        "public_ip": ip,
        "country": geo.get("country_name", "unknown"),
        "country_code": geo.get("country_code", "unknown"),
        "region": geo.get("region", "unknown"),
        "city": geo.get("city", "unknown"),
        "org": geo.get("org", "unknown"),
    }

    return {
        "statusCode": 200,
        "body": json.dumps(result, indent=2),
        "headers": {"Content-Type": "application/json"},
    }


def _get_public_ip():
    with urllib.request.urlopen("https://api.ipify.org?format=json", timeout=5) as r:
        return json.loads(r.read())["ip"]


def _geolocate(ip):
    url = f"https://ipapi.co/{ip}/json/"
    req = urllib.request.Request(url, headers={"User-Agent": "el-somer-brero-poc/1.0"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())
