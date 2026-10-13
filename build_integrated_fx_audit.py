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
    macro_data=read("fx_macro_snapshot.json")
    macro_raw=read("fx_macro_raw.json")
    macro_news=read("fx_macro_news.json")
    fusions=read("fx_unified_signals.json")
    actuals=read("fx_economic_actuals.json")
    cftc=read("fx_cftc_tff.json")
    range_data=read("fx_range_context.json")
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
    # Collection age and publisher quote age are NOT the same. A dated daily
    # value may be usable for historical context but cannot confirm 15m moves.
    for name,obj,field,limit in [
        ("macro_snapshot",macro_data,"generated_at_utc",45),
        ("macro_raw",macro_raw,"collected_at_utc",45),
        ("macro_news",macro_news,"generated_at_utc",45),
        ("unified_signals",fusions,"generated_at_utc",45),
        ("economic_actuals",actuals,"collected_at_utc",60),
        ("range_context",range_data,"generated_at_utc",45)]:
        minutes=age((obj or {}).get(field),now)
        sources[name]={"status":"FRESH" if minutes is not None and -2<=minutes<=limit
                       else "STALE" if minutes is not None else "MISSING",
                       "age_minutes":minutes}
    fresh_macro=sources["macro_snapshot"]["status"]=="FRESH"
    coverage=(macro_data or {}).get("source_coverage",{}) if fresh_macro else {}
    raw=(macro_raw or {}) if sources["macro_raw"]["status"]=="FRESH" else {}
    raw_ind=(raw.get("indices") or {})
    news_sources=(macro_news or {}).get("news_source_statuses",{}) if sources["macro_news"]["status"]=="FRESH" else {}
    market_data=(market or {}).get("pairs",{}) if sources["ff_markets"]["status"]=="FRESH" else {}
    retail_available=sum(bool(x.get("positioning")) for x in market_data.values())
    fxstreet=news_sources.get("FXStreet_RSS")
    reuters=news_sources.get("Reuters_currency_page")
    macro={
        "reuters_fxstreet_catalysts":(
            "PARTIAL_FXSTREET_DATED_HEADLINES_REUTERS_INACCESSIBLE"
            if fxstreet=="DATED_HEADLINES" and reuters!="DATED_HEADLINES" else
            "PARTIAL_DATED_HEADLINES_NOT_CAUSAL_VERIFICATION"
            if fxstreet=="DATED_HEADLINES" or reuters=="DATED_HEADLINES" else "UNAVAILABLE"),
        "calendar_schedule":(
            "VERIFIED_WEEKLY_SCHEDULE_NO_OFFICIAL_ACTUALS"
            if (cal or {}).get("status")=="VERIFIED" and sources["calendar"]["status"]=="FRESH" else "UNAVAILABLE"),
        "economic_actuals":(
            "PARTIAL_PUBLISHER_REPORTED_NO_OFFICIAL_RELEASE_CLOCK"
            if coverage.get("forexfactory_actuals")=="REPORTED_ACTUALS" else "UNAVAILABLE"),
        "sovereign_yield_differentials":(
            "PARTIAL_DATED_YIELD_TABLES_NO_VERIFIED_INTRADAY_QUOTE_TIME"
            if coverage.get("yield_observations_count",0)>=7 else "UNAVAILABLE"),
        "policy_rates":(
            "PUBLISHED_POLICY_RATE_REFERENCES_NOT_CURRENT_OIS"
            if coverage.get("policy_observations_count",0)>=5 else "UNAVAILABLE"),
        "ois":"UNAVAILABLE_NO_VALIDATED_PUBLIC_OIS",
        "commodities":(
            "PARTIAL_OILPRICE_DELAYED_AND_FOREXCRACKED_INDICATIVE"
            if coverage.get("commodity_observations_count",0)>0 else "UNAVAILABLE"),
        "dxy_equities_sentiment":(
            "PARTIAL_DATED_DXY_NIKKEI_KOSPI_CHINA_FEAR_GREED"
            if coverage.get("index_observations_count",0)>0 else "UNAVAILABLE"),
        "cftc_tff_positioning":(
            "VERIFIED_WEEKLY_HISTORICAL_NOT_REALTIME"
            if (cftc or {}).get("status")=="VERIFIED_HISTORICAL" else "UNAVAILABLE"),
        "cme_volume_open_interest":"PARTIAL_CFTC_WEEKLY_OI_CME_DAILY_DATA_UNVERIFIED",
        "retail_positioning":(
            "PARTIAL_PUBLIC_MARKET_POSITIONING" if retail_available>0 else "UNAVAILABLE_CURRENT"),
        "currency_strength_clusters":"DERIVED_FROM_11_FX_PAIRS",
        "closed_15m30m_direction":(
            "FRESH_TECHNICAL_WATCH_NOT_BROKER_EXECUTION"
            if sources["dashboard"]["status"]=="FRESH" else "STALE_OR_UNAVAILABLE"),
        "atr_adr_session_levels":(
            "PARTIAL_OR_COMPLETE_REFERENCE_CONTEXT_NOT_EXECUTION"
            if sources["range_context"]["status"]=="FRESH" else "PARTIAL_LEGACY_ATR_LEVELS"),
        "independent_live_spreads":"UNAVAILABLE_BROKER_EXECUTABLE_QUOTE",
        "signal_history":"VERIFIED_RECORDED_SIGNAL_OBSERVATIONS",
        "kospi_asian_equities":(
            "DATED_DAILY_CONTEXT_NOT_INTRADAY_KRX"
            if (asian_daily or (raw_ind.get("KOSPI") or {}).get("status")=="DATED_REFERENCE")
            else "UNAVAILABLE")}
    # Exact options layer has been removed at user request.
    fusion_fresh=sources["unified_signals"]["status"]=="FRESH"
    fusion_rows={x.get("pair"):x for x in ((fusions or {}).get("all_11",[]) if fusion_fresh else [])}
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
        unified=fusion_rows.get(pair,{})
        direction=unified.get("technical_direction_last_known") or rank.get("direction")
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
                        "technical_stage":unified.get("technical_stage") or rank.get("stage","UNRANKED"),
                        "unified_signal_direction":unified.get("direction") or "UNAVAILABLE",
                        "macro_alignment":unified.get("macro_alignment") or "UNKNOWN",
                        "macro_evidence":unified.get("macro_directional_evidence",[]),
                        "publisher_reported_actuals":unified.get("recent_publisher_actuals",[]),
                        "range_context":unified.get("range_context",{"status":"UNAVAILABLE"}),
                        "technical_15m30m_fresh":unified.get("technical_15m30m_fresh",False),
                        "early_watches_permitted_with_unknown_macro":True,"reference_level_not_live":rank.get("conditional_level_reference_only"),
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
                        "execution_status":"RESEARCH_EARLY_WATCH_NOT_EXECUTABLE"
                          if unified.get("signal_classification")=="EARLY_PROVISIONAL_WATCH"
                          else "RESEARCH_DIRECTIONAL_WATCH_NOT_EXECUTABLE",
                        "entry":None,"stop":None,"tp1":None,"tp2":None})
    output={"generated_at_utc":now.isoformat(),"purpose":"FULL_SOURCE_AUDIT_NOT_EXECUTABLE_TRADE_ORDERS",
            "sources":sources,"macro_layers":macro,"asian_risk_context":asian_summary,
            "pair_count":len(results),"pairs":results,
            "fully_macro_verified":False,
            "unified_signal_generated_at_utc":(fusions or {}).get("generated_at_utc"),
            "no_mobile_alerts":True,"options_layer":"REMOVED_AT_USER_REQUEST",
            "calendar_first_rule":"Every pair MUST display all upcoming events for both currencies in next 24 hours, regardless of impact. IMMINENT within 120 minutes prevents a normal entry signal; include forecasts and previous values. Do not infer releases from missing actuals.","unverified_layers":[k for k,v in macro.items()
                                 if "UNAVAILABLE" in v or "PARTIAL" in v or "STALE" in v],
            "rule":"Never present technical watches as macro-confirmed or executable trades"}
    Path("fx_integrated_audit.json").write_text(json.dumps(output,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"pairs":len(results),"source_statuses":{k:v["status"] for k,v in sources.items()},"macro_verified":False}))
if __name__=="__main__":main()
