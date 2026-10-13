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
    asian=read("fx_asian_risk.json")
    sources={}
    for name,obj,field,limit in [("technicals",tech,"collected_at_utc",30),("dashboard",dash,"generated_at_utc",30),("calendar",cal,"collected_at_utc",180),("ff_markets",market,"collected_at_utc",30),("volatility",vol,"collected_at_utc",30)]:
        minutes=age(obj.get(field),now) if isinstance(obj,dict) else None
        sources[name]={"status":"FRESH" if minutes is not None and 0<=minutes<=limit else "STALE" if minutes is not None else "MISSING","age_minutes":minutes}
    # Public page provides dated OTC/CFD daily KOSPI reference, NOT live KRX data.
    asian_age=age((asian or {}).get("collected_at_utc"),now)
    asian_fresh=asian_age is not None and -2<=asian_age<=40
    asian_daily=(asian_fresh and (asian or {}).get("daily_reference_status")==
                 "DATED_PUBLIC_DAILY_CFD_REFERENCE")
    asian_news=(asian_fresh and bool((asian or {}).get("intraday_news_summary")))
    sources["kospi_te_public_page"]={
        "status":"DATED_DAILY_CONTEXT" if asian_daily else
                 "DATED_NEWS_CONTEXT_ONLY" if asian_news else
                 "STALE" if asian_age is not None else "MISSING",
        "age_minutes":asian_age,
        "source_url":"https://tradingeconomics.com/south-korea/stock-market",
        "verified_intraday_quote":False}
    asian_summary={
        "source":"Trading Economics public KOSPI page (no key)",
        "status":sources["kospi_te_public_page"]["status"],
        "daily_reference_change_pct":(asian or {}).get("daily_reference_change_pct") if asian_daily else None,
        "daily_reference_level":(asian or {}).get("daily_reference_level") if asian_daily else None,
        "reference_date_kst":(asian or {}).get("reference_date_kst") if asian_daily else None,
        "risk_tier":(asian or {}).get("risk_tier_from_daily_reference") if asian_daily else "UNAVAILABLE",
        "dated_news_headline":(asian or {}).get("intraday_news_summary") if asian_news else None,
        "dated_news_day":(asian or {}).get("intraday_news_date") if asian_news else None,
        "interpretation":"Risk-off corroboration only; no verified intraday quote or automatic FX direction changes",
        "verified_intraday_quote":False,"execution_allowed":False}
    # Source presence is not evidence of verified macro fundamentals.
    macro={"reuters_fxstreet_catalysts":"UNAVAILABLE_AUTOMATED","sovereign_yield_differentials":"UNAVAILABLE_AUTOMATED",
           "ois":"UNAVAILABLE_AUTOMATED","commodities":"UNAVAILABLE_AUTOMATED",
           "cftc_cme_options":"UNAVAILABLE_AUTOMATED","independent_live_spreads":"UNAVAILABLE_AUTOMATED",
           "kospi_asian_equities":("DATED_DAILY_REFERENCE_PARTIAL" if asian_daily else
                                   "DATED_NEWS_PARTIAL" if asian_news else "UNAVAILABLE_AUTOMATED")}
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
                if dt and now-timedelta(minutes=15)<=dt<=now+timedelta(hours=48):
                    events.append({"title":e.get("title"),"currency":e.get("currency"),"impact":e.get("impact"),"event_at_et":e.get("event_at_et"),"forecast":e.get("forecast"),"previous":e.get("previous"),"actual":e.get("actual"),"minutes_until":round((dt-now).total_seconds()/60),"time_status":"IMMINENT" if -15<=((dt-now).total_seconds()/60)<=120 else "UPCOMING"})
        events.sort(key=lambda e:e.get("event_at_et") or "")
        next_24h=[e for e in events if 0<=e["minutes_until"]<=1440]
        imminent=[e for e in events if -15<=e["minutes_until"]<=120]
        event_risk="IMMINENT_EVENT" if imminent else "EVENT_WITHIN_24H" if next_24h else "NO_SCHEDULED_EVENT_24H"
        calendar_coverage="VERIFIED" if sources["calendar"]["status"]=="FRESH" and (cal or {}).get("status")=="VERIFIED" else "UNVERIFIED"
        ff=(market or {}).get("pairs",{}).get(pair,{}) if sources["ff_markets"]["status"]=="FRESH" else {}
        results.append({"pair":pair,"technical_direction":direction or "NO_RANKED_CANDIDATE",
                        "technical_stage":rank.get("stage","UNRANKED"),"reference_level_not_live":rank.get("conditional_level_reference_only"),
                        "h1_ema20_50":h1,"h4_ema20_50":h4,
                        "timeframes_present":all(tf.get("status")=="ok" for tf in (t15,t30,one,four)),
                        "higher_timeframe_conflict":conflict,"upcoming_48h_events":events,"next_24h_events":next_24h,"imminent_events":imminent,"event_risk":event_risk,"calendar_coverage":calendar_coverage,
                        "forexfactory_positioning":ff.get("positioning"),
                        "asian_risk_context":asian_summary if (
                            "JPY" in pair or "AUD" in pair or "NZD" in pair) else
                            {"status":asian_summary["status"],
                             "note":"General risk backdrop; not an FX trade signal"},
                        "asian_risk_directional_note":(
                            "KOSPI weakness can corroborate JPY buying if 15m/30m JPY crosses agree"
                            if pair.endswith("JPY") else
                            "Asian equity risk may affect AUD/NZD, but FX must confirm"
                            if ("AUD" in pair or "NZD" in pair) else
                            "Not a direct directional driver"),
                        "macro_confirmed":False,
                        "execution_status":"NO_TRADE_UNVERIFIED" if sources["technicals"]["status"]!="FRESH" or conflict or calendar_coverage!="VERIFIED" or imminent else "TECHNICAL_WATCH_MACRO_UNVERIFIED",
                        "entry":None,"stop":None,"tp1":None,"tp2":None})
    output={"generated_at_utc":now.isoformat(),"purpose":"FULL_SOURCE_AUDIT_NOT_EXECUTABLE_TRADE_ORDERS",
            "sources":sources,"macro_layers":macro,"asian_risk_context":asian_summary,
            "pair_count":len(results),"pairs":results,
            "fully_macro_verified":False,"calendar_first_rule":"Every pair MUST display all upcoming events for both currencies in next 24 hours, regardless of impact. IMMINENT within 120 minutes prevents a normal entry signal; include forecasts and previous values. Do not infer releases from missing actuals.","unverified_layers":[k for k,v in macro.items() if v!="VERIFIED"],
            "rule":"Never present technical watches as macro-confirmed or executable trades"}
    Path("fx_integrated_audit.json").write_text(json.dumps(output,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"pairs":len(results),"source_statuses":{k:v["status"] for k,v in sources.items()},"macro_verified":False}))
if __name__=="__main__":main()
