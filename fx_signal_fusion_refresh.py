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

def enrich_source_context(rows, now, dashboard, early, ff_market, levels, history, raw):
    """Add provenance-aware contextual data, never change candle BUY/SELL or rank.

    Forex Factory market pages frequently omit JS-rendered prices and spreads;
    those missing fields must stay null, not become broker quotes. Source
    download clocks are never substituted for quote publication timestamps.
    """
    def available(doc, field, age_limit):
        age = age_min(doc.get(field), now)
        return age is not None and -2 <= age <= age_limit

    ff_ok = available(ff_market, "collected_at_utc", 90)
    levels_ok = (available(levels, "generated_at_utc", 20)
                 and levels.get("generated_at_utc") ==
                 dashboard.get("daily_weekly_levels_generated_at_utc"))
    raw_ok = available(raw, "collected_at_utc", 45)
    breadth = dashboard.get("currency_strength_breadth") or {}
    cluster = early.get("jpy_cluster") or dashboard.get("early_rotation_jpy_cluster") or {}
    historic = history.get("pairs") or {}
    for row in rows:
        pair = row["pair"]
        ff = (ff_market.get("pairs") or {}).get(pair, {}) if ff_ok else {}
        published = (levels.get("pairs") or {}).get(pair, {}) if levels_ok else {}
        h = historic.get(pair, {}) if isinstance(historic, dict) else {}
        active = h.get("active") if isinstance(h, dict) else None
        active_ok = isinstance(active, dict) and available(active, "last_observed_at_utc", 20)
        p1, p2 = pair[:3], pair[3:]
        policies = (raw.get("policy_rates") or {}) if raw_ok else {}
        row["policy_rate_context"] = {
            c: {"reference_rate_pct": policies.get(c, {}).get("policy_rate_pct"),
                "reference_date": policies.get(c, {}).get("reference_date"),
                "source": policies.get(c, {}).get("url"),
                "status": policies.get(c, {}).get("status", "UNAVAILABLE"),
                "ois_verified": False}
            for c in (p1, p2)}
        row["ois_reference"] = raw.get("ois", {"status": "UNAVAILABLE_STALE"}) if raw_ok else {
            "status": "UNAVAILABLE_STALE"}
        row["cme_reference"] = raw.get("cme_futures", {"status": "UNAVAILABLE"}) if raw_ok else {
            "status": "UNAVAILABLE_STALE"}
        row["forexfactory_market_context"] = {
            "status": ff.get("status", "UNAVAILABLE_STALE_OR_BLOCKED"),
            "source_url": ff.get("source_url") if ff_ok else None,
            "fetched_at_utc": ff.get("fetched_at_utc") if ff_ok else None,
            "price": ff.get("price"),
            "price_status": ff.get("price_status", "UNAVAILABLE_UNVERIFIED"),
            "spread": ff.get("spread"),
            "spread_status": ff.get("spread_status", "UNAVAILABLE_UNVERIFIED"),
            "positioning": ff.get("positioning"),
            "broker_executable": False, "directional_vote": False}
        row["daily_weekly_price_levels"] = published if published else {
            "status": "UNAVAILABLE_STALE_OR_UNSYNCHRONIZED"}
        row["currency_strength_cluster_context"] = {
            "base_breadth": breadth.get(p1),
            "quote_breadth": breadth.get(p2),
            "from": "CLOSED_15M_30M_TECHNICALS",
            "jpy_cluster": cluster.get("status", "UNAVAILABLE") if "JPY" in pair else None,
            "cross_specific": (cluster.get("pairs") or {}).get(pair) if "JPY" in pair else None,
            "directional_signal_input": False}
        row["signal_episode_history"] = {
            "status": "CURRENT_RECORDED_EPISODE" if active_ok else "UNAVAILABLE_STALE_OR_INACTIVE",
            "active": active if active_ok else None,
            "previous_episode_count": len(h.get("history") or []) if isinstance(h, dict) else 0,
            "no_future_candle_lookahead": True,
            "directional_vote": False}
        row["context_freshness_flags"] = {
            "forexfactory_markets": "FRESH_FETCH_NOT_QUOTE" if ff_ok else "STALE_OR_MISSING",
            "daily_weekly_levels": "SYNCHRONIZED" if levels_ok else "STALE_OR_UNSYNCHRONIZED",
            "policy_reference": "FRESH_FETCH_NOT_POLICY_UPDATE" if raw_ok else "STALE_OR_MISSING",
            "signal_history": "RECORDED" if active_ok else "STALE_OR_INACTIVE"}
    return rows


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
    retail=read("fx_retail_positioning.json")
    ff_market=read("fx_forexfactory_markets.json")
    levels=read("fx_daily_weekly_levels.json")
    history=read("fx_signal_history.json")
    if not fresh(retail,"collected_at_utc",90,now):
        retail={}
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
                     spreads,deltas,metrics,cftc,(raw if raw_ok else {}),now,
                     retail=retail)
    enrich_source_context(rows, now, dash, early, ff_market, levels, history,
                          raw if raw_ok else {})
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
         "macro_snapshot_used":macro_ok,
         "context_contract": "MARKET_REFERENCES_AND_MISSING_DATA_NON_EXECUTABLE",
         "source_freshness_minutes":{
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
