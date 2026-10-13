#!/usr/bin/env python3
"""No-key Forex Factory calendar HTML actuals: separately verify reported results.

The weekly JSON contains times/forecasts but no actuals. The public HTML page
may provide Actual/Forecast/Previous. Match uniquely by currency+exact title
to a past scheduled weekly event; never infer actuals from future/missing cells.
"""
import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from bs4 import BeautifulSoup

URL = "https://www.forexfactory.com/calendar?week=this"
PAIRS = ("AUDUSD", "NZDUSD", "EURUSD", "GBPUSD", "USDJPY",
         "AUDJPY", "NZDJPY", "EURJPY", "EURCAD", "USDCAD", "EURGBP")

def norm(x):
    return re.sub(r"[^a-z0-9]+", " ", str(x).lower()).strip()

def parse(html, calendar, now=None):
    now = now or datetime.now(timezone.utc)
    out = {"collected_at_utc": now.isoformat(), "source": "Forex Factory public HTML",
           "url": URL, "status": "UNAVAILABLE", "actuals": [],
           "source_type": "PUBLISHER_REPORTED_NOT_OFFICIAL_RELEASE_VERIFICATION"}
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("tr.calendar__row")
    if not rows:
        out["status"] = "UNAVAILABLE_NO_RECOGNIZED_CALENDAR_ROWS"
        return out
    observed = {}
    for tr in rows:
        def cell(name):
            el = tr.select_one(".calendar__" + name)
            return el.get_text(" ", strip=True) if el else ""
        currency = cell("currency").upper()
        title = cell("event")
        actual = cell("actual")
        if currency not in {"AUD", "NZD", "EUR", "GBP", "USD", "JPY", "CAD", "CNY"}:
            continue
        if not title or not actual or actual in {"--", "-", "N/A"}:
            continue
        key = (currency, norm(title))
        observed.setdefault(key, []).append({
            "currency": currency, "title": title,
            "actual": actual, "page_forecast": cell("forecast"),
            "page_previous": cell("previous")})
    # Only retain unique currency/title across week, no guessed event dates
    counts = {}
    for ev in (calendar or {}).get("events", []):
        key = (str(ev.get("currency", "")).upper(), norm(ev.get("title", "")))
        counts[key] = counts.get(key, 0) + 1
    for ev in (calendar or {}).get("events", []):
        key = (str(ev.get("currency", "")).upper(), norm(ev.get("title", "")))
        possible = observed.get(key, [])
        if counts[key] != 1 or len(possible) != 1:
            continue
        try:
            scheduled = datetime.fromisoformat(str(ev["event_at_utc"]).replace("Z", "+00:00"))
        except (ValueError, TypeError, KeyError):
            continue
        if scheduled.tzinfo is None or scheduled > now:
            continue
        # An actual visible on a weekly page is not proof of exact release clock.
        # No intraday timing claim, and no surprise sign/direction inferred here.
        row = possible[0]
        out["actuals"].append({
            "currency": key[0], "title": ev["title"],
            "scheduled_at_utc": scheduled.isoformat(),
            "reported_actual": row["actual"],
            "forecast": ev.get("forecast") or row["page_forecast"],
            "previous": ev.get("previous") or row["page_previous"],
            "source": URL, "verified_at_utc": now.isoformat(),
            "released_at_utc": None,
            "status": "PUBLIC_PAGE_REPORTED_ACTUAL_RELEASE_TIME_UNVERIFIED",
            "match_method": "UNIQUE_EXACT_TITLE_CURRENCY_WITH_PAST_WEEKLY_EVENT"})
    out["status"] = "REPORTED_ACTUALS" if out["actuals"] else "NO_MATCHED_PUBLISHED_ACTUALS"
    out["actuals"].sort(key=lambda e: e["scheduled_at_utc"], reverse=True)
    out["actuals"] = out["actuals"][:120]
    return out

def main():
    now = datetime.now(timezone.utc)
    try:
        cal = json.loads(Path("fx_economic_calendar.json").read_text(encoding="utf-8"))
    except (ValueError, OSError):
        cal = {}
    try:
        req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (compatible; FXResearch/1.0)"})
        with urllib.request.urlopen(req, timeout=18) as res:
            html = res.read(1_600_000).decode("utf-8", "replace")
        result = parse(html, cal, now)
    except Exception as exc:
        result = {"collected_at_utc": now.isoformat(), "source": URL,
                  "status": "UNAVAILABLE_" + type(exc).__name__.upper(),
                  "actuals": [], "error": str(exc)[:180]}
    Path("fx_economic_actuals.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "matched_actuals": len(result["actuals"])}))

if __name__ == "__main__":
    main()
