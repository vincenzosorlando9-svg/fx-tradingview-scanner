#!/usr/bin/env python3
"""Fast technical-triggered fused board refresh; never re-sample macro raw snapshots.

Macro collectors publish no-key history/snapshots nominally every 15m.
This adapter runs after the existing M15/M30 scanner (~5m) using the most
recent honest macro snapshot with timestamp gating, but does not claim any
new macro quote or update macro-history just because GitHub ran again.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from fx_macro_collector import PAIRS
from fx_macro_engine import (age_min, build_pairs, read, write)

UTC=timezone.utc

def fresh(obj, field, max_m, now):
    age=age_min(obj.get(field),now)
    return age is not None and -2<=age<=max_m

def refresh(now=None):
    now=now or datetime.now(UTC)
    dash=read("fx_scan_dashboard.json")
    early=read("fx_early_rotation.json")
    if not fresh(dash,"generated_at_utc",15,now):
        raise RuntimeError("TECHNICAL_DASHBOARD_STALE_NO_UNIFIED_PUBLICATION")
    if not fresh(early,"generated_at_utc",15,now):
        raise RuntimeError("EARLY_ROTATION_STALE_NO_UNIFIED_PUBLICATION")
    if not dash.get("source_versions_match"):
        raise RuntimeError("DASHBOARD_INPUTS_NOT_SYNCHRONIZED")
    if len(dash.get("pairs",[]))!=len(PAIRS) or len(early.get("pairs",[]))!=len(PAIRS):
        raise RuntimeError("NOT_ALL_11_TECHNICAL_PAIRS_PRESENT")
    snap=read("fx_macro_snapshot.json")
    news=read("fx_macro_news.json")
    raw=read("fx_macro_raw.json")
    range_data=read("fx_range_context.json")
    cal=read("fx_economic_calendar.json")
    cftc=read("fx_cftc_tff.json")
    macro_ok=fresh(snap,"generated_at_utc",45,now)
    raw_ok=fresh(raw,"collected_at_utc",45,now)
    news_ok=fresh(news,"generated_at_utc",60,now)
    range_ok=fresh(range_data,"generated_at_utc",45,now)
    metrics=snap.get("metrics",{}) if macro_ok else {}
    spreads=snap.get("same_maturity_yield_spreads",{}) if macro_ok else {}
    deltas=snap.get("observed_fetch_deltas",{}) if macro_ok else {}
    if not isinstance(metrics,dict) or not isinstance(spreads,dict) or not isinstance(deltas,dict):
        metrics,spreads,deltas={},{},{}
        macro_ok=False
    rows=build_pairs(dash,early,cal,(news if news_ok else {"articles":[],"matched_actuals":[]}),
                     spreads,deltas,metrics,cftc,(raw if raw_ok else {}),now)
    for row in rows:
        ctx=(range_data.get("pairs") or {}).get(row["pair"]) if range_ok else None
        row["range_context"]=ctx or {"status":"UNAVAILABLE_STALE_OR_MISSING_RANGE_REFERENCE"}
        row["range_data_is_directional_signal"]=False
        row["session_liquidity_context"]={
            "upcoming_2h_event":row["event_within_120_minutes"],
            "holiday_on_calendar":any(str(x.get("impact","")).lower()=="holiday"
                                      for x in row.get("economic_events_next_24h",[])),
            "broker_spread_verified":False,
            "liquidity_interpretation":"SCHEDULED_SESSION_AND_EVENT_CONTEXT_NOT_MEASURED_ORDERBOOK"}
    doc={"schema_version":1, "generated_at_utc":now.isoformat(),
         "source_technical_generated_at_utc":dash.get("generated_at_utc"),
         "source_early_rotation_generated_at_utc":early.get("generated_at_utc"),
         "source_macro_collected_at_utc":(raw if raw_ok else {}).get("collected_at_utc"),
         "scope":"11_PAIR_RESEARCH_ONLY_NO_ORDERS_OR_ALERTS",
         "signals_from":"CLOSED_15M_30M_ONLY",
         "context_from":"1H_4H_DAILY_AND_MACRO",
         "macro_missing_does_not_veto_early_technical_direction":True,
         "ranking_policy":"50pct_early_opportunity_plus_50pct_trend_strength; macro independent",
         "no_mobile_alerts":True,"real_broker_spread_verified":False,
         "macro_snapshot_used":macro_ok,"source_freshness_minutes":{
             "macro_snapshot":round(age_min(snap.get("generated_at_utc"),now),1)
                              if snap.get("generated_at_utc") else None,
             "news":round(age_min(news.get("generated_at_utc"),now),1)
                              if news.get("generated_at_utc") else None,
             "range":round(age_min(range_data.get("generated_at_utc"),now),1)
                              if range_data.get("generated_at_utc") else None},
         "top_five":rows[:5],"all_11":rows,"pair_count":len(rows),
         "integrity":snap.get("source_coverage",{}) if macro_ok else
                      {"macro":"UNAVAILABLE_OR_STALE_TRADE_WATCH_STAYS_TECHNICAL"}}
    if {row["pair"] for row in rows} != set(PAIRS) or len(rows)!=11:
        raise RuntimeError("UNIFIED_SCOPE_INTEGRITY_FAILED")
    if any(x.get("trade_execution_allowed") or not x.get("no_5m_signal_inputs") for x in rows):
        raise RuntimeError("TRADING_SAFETY_RULE_FAILED")
    write("fx_unified_signals.json",doc)
    return doc

def main():
    output=refresh()
    print(json.dumps({"pairs":output["pair_count"],
                      "macro_available":output["macro_snapshot_used"],
                      "macro_snapshot_age_minutes":output["source_freshness_minutes"]["macro_snapshot"],
                      "first":output["top_five"][0]["pair"],
                      "new_macro_snapshot_generated":False,
                      "source":"latest_closed_M15_M30"}))

if __name__=="__main__":
    main()
