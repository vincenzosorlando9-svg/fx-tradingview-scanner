"""Trading Economics market snapshots. Requires a licensed TE_API_KEY GitHub secret.
Research data only: no orders, no implied real-time status without source timestamps.
"""
import json, os, sys, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://api.tradingeconomics.com"
CATEGORIES = ("currency", "commodity", "bond", "index")
OUT = Path("fx_macro_snapshot.json")

def utcnow():
    return datetime.now(timezone.utc).isoformat()

def fetch(category, key):
    req = urllib.request.Request(
        f"{BASE}/markets/{category}?f=json",
        headers={"Authorization": key, "Accept": "application/json",
                 "User-Agent": "fx-tradingview-scanner/1.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
        data = json.load(response)
    if not isinstance(data, list):
        raise ValueError(f"{category}: expected list; API may have rejected subscription")
    return data

def normalize(item):
    return {
        "symbol": item.get("Symbol"),
        "name": item.get("Name"),
        "last": item.get("Last"),
        "daily_change": item.get("DailyChange"),
        "daily_percent_change": item.get("DailyPercentualChange"),
        "date": item.get("Date"),
        "raw": item
    }

def main():
    key = os.getenv("TE_API_KEY", "").strip()
    output = {"collected_at_utc": utcnow(), "provider": "Trading Economics API",
              "quote_realtime_status": "UNVERIFIED_CHECK_INSTRUMENT_SOURCE_DATE",
              "status": "UNAVAILABLE", "categories": {}, "errors": [],
              "notes": ["Collection time does not establish quote time or real-time entitlement.",
                        "No signal or trade is authorized by this snapshot."]}
    if not key:
        output["errors"].append("TE_API_KEY_NOT_CONFIGURED")
    else:
        for category in CATEGORIES:
            try:
                rows = fetch(category, key)
                output["categories"][category] = {
                    "status": "COLLECTED_UNVERIFIED_QUOTE_FRESHNESS",
                    "count": len(rows),
                    "items": [normalize(x) for x in rows if isinstance(x, dict)]
                }
            except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
                output["categories"][category] = {"status": "UNAVAILABLE", "count": 0, "items": []}
                output["errors"].append(f"{category}:{type(exc).__name__}")
        output["status"] = ("COLLECTED_PARTIAL_OR_UNVERIFIED" if output["categories"]
                            else "UNAVAILABLE")
    OUT.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print("TE macro collection:", output["status"],
          {k:v["count"] for k,v in output["categories"].items()}, output["errors"])
    if output["errors"]:
        sys.exit(1)

if __name__ == "__main__":
    main()
