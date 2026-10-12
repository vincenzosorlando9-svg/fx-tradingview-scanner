#!/usr/bin/env python3
"""Merge available FX sources into a single honest, timestamped decision board."""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

PAIRS=["AUDUSD","NZDUSD","EURUSD","GBPUSD","USDJPY","AUDJPY","NZDJPY","EURJPY","EURCAD","USDCAD","EURGBP"]
def read(path):
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,ValueError): return None
def date(s):
    try: return datetime.fromisoformat(s.replace("Z","+00:00")).astimezone(timezone.utc)
    except (TypeError,ValueError,AttributeError): return None
def age(s,now):
    d=date(s)
    return round((now-d).total_seconds()/60,1) if d else None
def main():
    now=datetime.now(timezone.utc)
    dash=read("fx_scan_dashboard.json")
    tech=read("fx_technicals.json")
    cal=read("fx_economic_calendar.json")
    market=read("fx_forexfactory_markets.json")
    vol=read("fx_volatility.json")
    sources={}
    for name,obj,field,limit in [("technicals",tech,"collected_at_utc",30),("dashboard",dash,"generated_at_utc",30),("calendar",cal,"collected_at_utc",180),("ff_markets",market,"collected_at_utc",30),("volatility",vol,"collected_at_utc",30)]:
        minutes=age(obj.get(field),now) if isinstance(obj,dict) else None
        sources[name]={"status":"FRESH" if minutes is not None and 0<=minutes<=limit else "STALE" if minutes is not None else "MISSING","age_minutes":minutes}
    # Source presence is not evidence of verified macro fundamentals.
    macro={"reuters_fxstreet_catalysts":"UNAVAILABLE_AUTOMATED","sovereign_yield_differentials":"UNAVAILABLE_AUTOMATED",
           "ois":"UNAVAILABLE_AUTOMATED","commodities":"UNAVAILABLE_AUTOMATED",
           "cftc_cme_options":"UNAVAILABLE_AUTOMATED","independent_live_spreads":"UNAVAILABLE_AUTOMATED"}
    ranks={x.get("pair"):x for x in (dash or {}).get("top_five_technical_candidates",[])}
    results=[]
    for pair in PAIRS:
        timeframes=(tech or {}).get("pairs",{}).get(pair,{})
        one=timeframes.get("1H",{})
        four=timeframes.get("4H",{})
        t15=timeframes.get("15m",{})
        t30=timeframes.get("30m",{})
        def relation(tf):
            i=tf.get("indicators") or {}
            price=i.get("close"); e20=i.get("EMA20"); e50=i.get("EMA50")
            if not all(isinstance(x,(float,int)) for x in (price,e20,e50)):return "UNKNOWN"
            return "ABOVE_BOTH" if price>e20 and price>e50 else "BELOW_BOTH" if price<e20 and price<e50 else "MIXED"
        h1=relation(one);h4=relation(four)
        rank=ranks.get(pair,{})
        direction=rank.get("direction")
        conflict=(direction=="SELL" and h1=="ABOVE_BOTH") or (direction=="BUY" and h1=="BELOW_BOTH")
        events=[]
        if isinstance(cal,dict) and sources["calendar"]["status"]=="FRESH":
            for e in cal.get("pairs",{}).get(pair,[]):
                dt=date(e.get("event_at_utc"))
                if dt and now<=dt<=now+timedelta(hours=48):
                    events.append({"title":e.get("title"),"currency":e.get("currency"),"impact":e.get("impact"),"event_at_et":e.get("event_at_et"),"forecast":e.get("forecast")})
        events.sort(key=lambda e:e.get("event_at_et") or "")
        ff=(market or {}).get("pairs",{}).get(pair,{}) if sources["ff_markets"]["status"]=="FRESH" else {}
        results.append({"pair":pair,"technical_direction":direction or "NO_RANKED_CANDIDATE",
                        "technical_stage":rank.get("stage","UNRANKED"),"reference_level_not_live":rank.get("conditional_level_reference_only"),
                        "h1_ema20_50":h1,"h4_ema20_50":h4,
                        "timeframes_present":all(tf.get("status")=="ok" for tf in (t15,t30,one,four)),
                        "higher_timeframe_conflict":conflict,"upcoming_48h_events":events,
                        "forexfactory_positioning":ff.get("positioning"),"macro_confirmed":False,
                        "execution_status":"NO_TRADE_UNVERIFIED" if sources["technicals"]["status"]!="FRESH" or conflict else "TECHNICAL_WATCH_MACRO_UNVERIFIED",
                        "entry":None,"stop":None,"tp1":None,"tp2":None})
    output={"generated_at_utc":now.isoformat(),"purpose":"FULL_SOURCE_AUDIT_NOT_EXECUTABLE_TRADE_ORDERS",
            "sources":sources,"macro_layers":macro,"pair_count":len(results),"pairs":results,
            "fully_macro_verified":False,"unverified_layers":[k for k,v in macro.items() if v!="VERIFIED"],
            "rule":"Never present technical watches as macro-confirmed or executable trades"}
    Path("fx_integrated_audit.json").write_text(json.dumps(output,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"pairs":len(results),"source_statuses":{k:v["status"] for k,v in sources.items()},"macro_verified":False}))
if __name__=="__main__":main()
