#!/usr/bin/env python3
"""Official weekly CFTC TFF futures-only currency positioning. Not real-time flow."""
import csv
import io
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://www.cftc.gov/dea/newcot/FinFutWk.txt"
CURRENCIES = {
    "CAD": "CANADIAN DOLLAR", "GBP": "BRITISH POUND",
    "JPY": "JAPANESE YEN", "EUR": "EURO FX",
    "AUD": "AUSTRALIAN DOLLAR", "NZD": "NEW ZEALAND DOLLAR",
}
# CFTC TFF SHORT FORMAT FUTURES ONLY fixed CSV order; parsed without options or swaps.
# 0 market, 2 observation date, 7 OI, 8-10 dealer (L,S,spread),
# 11-13 asset mgr (L,S,spread), 14-16 leveraged funds (L,S,spread).
def parse(body, now=None):
    now = now or datetime.now(timezone.utc)
    out = {"source": "CFTC official TFF futures-only weekly release", "url": URL,
           "collected_at_utc": now.isoformat(), "report_date": None,
           "status": "UNAVAILABLE", "currencies": {},
           "limitations": "Tuesday positioning, usually published Friday; not current intraday flow"}
    for row in csv.reader(io.StringIO(body)):
        if len(row) < 24:
            continue
        name = row[0].upper().strip()
        currency = next((c for c, label in CURRENCIES.items() if name.startswith(label + " - ")), None)
        if not currency:
            continue
        try:
            observed = datetime.fromisoformat(row[2]).date()
            days = (now.date() - observed).days
            if days < 0 or days > 21:
                continue
            fields = [int(row[i].strip()) for i in (7, 8, 9, 11, 12, 14, 15)]
            oi, dealer_l, dealer_s, asset_l, asset_s, lev_l, lev_s = fields
            if oi <= 0 or any(x < 0 or x > oi for x in fields[1:]):
                continue
        except (ValueError, IndexError):
            continue
        out["currencies"][currency] = {
            "report_date": observed.isoformat(),
            "open_interest_contracts": oi,
            "dealer_long": dealer_l, "dealer_short": dealer_s,
            "asset_mgr_long": asset_l, "asset_mgr_short": asset_s,
            "asset_mgr_net": asset_l - asset_s,
            "leveraged_long": lev_l, "leveraged_short": lev_s,
            "leveraged_net": lev_l - lev_s,
            "leveraged_net_share_open_interest_pct": round(100 * (lev_l - lev_s) / oi, 2),
            "status": "VERIFIED_WEEKLY_HISTORICAL_NOT_INTRADAY"}
        out["report_date"] = max(out["report_date"] or "", observed.isoformat())
    out["status"] = "VERIFIED_HISTORICAL" if len(out["currencies"]) >= 4 else "INCOMPLETE_OR_MISSING"
    return out

def main():
    now = datetime.now(timezone.utc)
    try:
        req = urllib.request.Request(URL, headers={
            "User-Agent": "Mozilla/5.0 FX-Macro-Research/1.0", "Accept": "text/plain"})
        with urllib.request.urlopen(req, timeout=22) as response:
            contents = response.read(400_000).decode("utf-8-sig", "replace")
        data = parse(contents, now)
    except Exception as exc:
        data = {"source": "CFTC official futures-only weekly TFF", "url": URL,
                "collected_at_utc": now.isoformat(),
                "status": "UNAVAILABLE_" + type(exc).__name__.upper(),
                "currencies": {}, "error": str(exc)[:150]}
    if data["status"] == "VERIFIED_HISTORICAL":
        Path("fx_cftc_tff.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    else:
        # Do not replace the latest verified historical weekly report with a network error.
        print(json.dumps({"status": data["status"], "written": False}))
        return
    print(json.dumps({"status": data["status"], "date": data["report_date"],
                      "currencies": list(data["currencies"])}))

if __name__ == "__main__":
    main()
