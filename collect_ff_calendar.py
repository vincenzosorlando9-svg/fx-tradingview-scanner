#!/usr/bin/env python3
"""No-key Forex Factory weekly calendar collector. Standard library only."""
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
PAIRS = ["AUDUSD","NZDUSD","EURUSD","GBPUSD","USDJPY","AUDJPY","NZDJPY","EURJPY","EURCAD","USDCAD","EURGBP"]
ET = ZoneInfo("America/New_York")
CURRENCIES = {"AUD","NZD","EUR","GBP","USD","JPY","CAD"}
IMPACTS = {"High","Medium","Low","Holiday"}
def relevant(pair, country):
    return country in (pair[:3], pair[3:], "All") or (country == "CNY" and ("AUD" in pair or "NZD" in pair))
def main():
    now = datetime.now(timezone.utc)
    result = {"collected_at_utc":now.isoformat(), "source":URL, "source_name":"Forex Factory / Fair Economy weekly calendar",
              "status":"MISSING","actuals_available":False,"actuals_note":"Weekly JSON has no actual field; verify official releases separately.",
              "timezone":"America/New_York","pairs":{p:[] for p in PAIRS},"events":[],"errors":[]}
    try:
        request=urllib.request.Request(URL,headers={"User-Agent":"FX-Macro-Calendar-Research/1.0","Accept":"application/json"})
        with urllib.request.urlopen(request,timeout=25) as response:
            if response.status != 200:
                raise RuntimeError("HTTP "+str(response.status))
            raw=response.read(1500000)
        payload=json.loads(raw)
        if not isinstance(payload,list):
            raise ValueError("Expected event array")
        for item in payload:
            if not isinstance(item,dict):
                continue
            country=str(item.get("country","")).upper().strip()
            if country not in CURRENCIES | {"CNY","All","CHF"}:
                continue
            if not all(k in item for k in ("title","country","date","impact")):
                continue
            when=datetime.fromisoformat(str(item["date"]).replace("Z","+00:00"))
            if when.tzinfo is None:
                continue
            impact=str(item["impact"]).strip().title()
            if impact not in IMPACTS:
                impact="Unknown"
            event={"title":str(item["title"]),"currency":country,"event_at_utc":when.astimezone(timezone.utc).isoformat(),
                   "event_at_et":when.astimezone(ET).isoformat(),"impact":impact,
                   "forecast":str(item.get("forecast") or ""),"previous":str(item.get("previous") or ""),
                   "actual":None,"actual_status":"UNAVAILABLE",
                   "time_relation":"UPCOMING" if when>now else "PAST_NOT_RELEASE_VERIFIED"}
            result["events"].append(event)
            for pair in PAIRS:
                if relevant(pair,country):
                    result["pairs"][pair].append(event)
        result["events"].sort(key=lambda x:x["event_at_utc"])
        for p in PAIRS:
            result["pairs"][p].sort(key=lambda x:x["event_at_utc"])
        result["event_count"]=len(result["events"])
        result["status"]="VERIFIED" if result["events"] else "PARTIAL"
        if not result["events"]:
            result["errors"].append("EMPTY_WEEKLY_FEED")
    except Exception as exc:
        result["errors"].append(type(exc).__name__+": "+str(exc))
        # Keep previous verified calendar on transient fetch failure; do not overwrite it.
        print(json.dumps({"status":"FETCH_FAILED","errors":result["errors"]}),file=sys.stderr)
        return 1
    path=os.environ.get("FF_CALENDAR_OUTPUT","fx_economic_calendar.json")
    with open(path+".tmp","w",encoding="utf-8") as f:
        json.dump(result,f,indent=2,ensure_ascii=False)
        f.write("\n")
    os.replace(path+".tmp",path)
    print(json.dumps({"status":result["status"],"events":len(result["events"]),"output":path}))
    return 0
if __name__=="__main__":
    sys.exit(main())
