#!/usr/bin/env python3
"""Immutable-by-default user-approved FULL FX scan presentation order.

Presentation only: no new trading signals, no fabricated broker quotes,
no rankings changed, and no 5-minute signal inputs.
"""
import json
from pathlib import Path

from fx_macro_collector import PAIRS

LAYOUT_VERSION = "USER_APPROVED_2026_10_13_STRENGTH_FIRST_V1"
PRESENTATION_ORDER = [
    "currency_strength",
    "best_five_trading_pairs",
    "five_detailed_trade_setups",
    "complete_market_intelligence",
    "all_11_pairs",
    "final_scan_conclusion",
]


def read(path):
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def build_report(unified, dashboard, raw=None, news=None, snapshot=None,
                 calendar=None, cftc=None, audit=None):
    """Reformat existing verified reports without altering a direction or rank."""
    raw, news, snapshot = raw or {}, news or {}, snapshot or {}
    calendar, cftc, audit = calendar or {}, cftc or {}, audit or {}
    all_pairs = unified.get("all_11") or []
    top = unified.get("top_five") or []
    if len(all_pairs) != 11 or {r.get("pair") for r in all_pairs} != set(PAIRS):
        raise ValueError("SCAN_LAYOUT_REQUIRES_ALL_11_APPROVED_PAIRS")
    if len(top) > 5 or len({r.get("pair") for r in top}) != len(top):
        raise ValueError("TOP_FIVE_INVALID")
    if any(r.get("pair") not in set(PAIRS) for r in top):
        raise ValueError("TOP_FIVE_OUTSIDE_APPROVED_UNIVERSE")
    if unified.get("source_technical_generated_at_utc") != dashboard.get("generated_at_utc"):
        raise ValueError("STRENGTH_AND_SIGNAL_SOURCE_TIMES_DIFFER")
    if unified.get("signals_from") != "CLOSED_15M_30M_ONLY":
        raise ValueError("REPORT_MUST_USE_CLOSED_15M_30M_SIGNAL_INPUTS")
    if any(r.get("trade_execution_allowed") for r in all_pairs):
        raise ValueError("AUTO_TRADE_NOT_ALLOWED")

    currencies = sorted({p[:3] for p in PAIRS} | {p[3:] for p in PAIRS})
    breadth = dashboard.get("currency_strength_breadth") or {}
    ordered = sorted(currencies, key=lambda c: (-breadth.get(c, 0), c))
    complete = all(c in breadth and isinstance(breadth[c], (int, float))
                   and not isinstance(breadth[c], bool) for c in currencies)
    strength_rows = [
        {"rank": i + 1, "currency": c,
         "breadth_score": breadth.get(c) if complete else None,
         "acceleration": None,
         "acceleration_status": "NOT_INDEPENDENTLY_VERIFIED"}
        for i, c in enumerate(ordered if complete else currencies)
    ]
    strength = {
        "status": "AVAILABLE_INDICATIVE_TECHNICAL_BREADTH" if complete
                  else "UNAVAILABLE_INCOMPLETE_BREADTH",
        "as_of_utc": dashboard.get("generated_at_utc"),
        "method": dashboard.get("currency_strength_note") or
                  "Unweighted 11-pair directional breadth; not independently measured currency strength",
        "strongest": [c for c in ordered if breadth.get(c) == breadth[ordered[0]]]
                     if complete else [],
        "weakest": [c for c in ordered if breadth.get(c) == breadth[ordered[-1]]]
                   if complete else [],
        "ranked_strongest_to_weakest": strength_rows,
        "caveat": "CLOSED_15M_30M_DIRECTIONAL_BREADTH_NOT_AN_INDEPENDENT_REALTIME_STRENGTH_FEED",
    }

    def board_item(row, rank):
        prices = row.get("reference_prices") or {}
        return {
            "rank": rank,
            "pair": row.get("pair"),
            "direction": row.get("direction"),
            "stage": row.get("technical_stage"),
            "research_score": row.get("technical_research_rank_score"),
            "early_opportunity_score_50pct": row.get("early_opportunity_score_50pct"),
            "trend_strength_score_50pct": row.get("trend_strength_score_50pct"),
            "macro_alignment": row.get("macro_alignment", "UNKNOWN"),
            "price_reference": prices.get("last_closed_15m"),
            "price_reference_closed_at_utc": prices.get("closed_at_utc"),
            "price_type": "LAST_CLOSED_15M_REFERENCE_NOT_EXECUTABLE",
            "entry_readiness": row.get("signal_classification"),
        }

    board = [board_item(row, rank) for rank, row in enumerate(top, 1)]
    setups = []
    for rank, row in enumerate(top, 1):
        prices = row.get("reference_prices") or {}
        setups.append({
            **board_item(row, rank),
            "first_detected_at_utc": row.get("signal_first_recorded_at_utc"),
            "conditional_entry": row.get("entry"),
            "stop_or_invalidation": row.get("stop"),
            "tp1": row.get("tp1"),
            "tp2": row.get("tp2"),
            "indicative_fx_reference": {
                "bid": prices.get("forexcracked_indicative_bid"),
                "ask": prices.get("forexcracked_indicative_ask"),
                "age_minutes": prices.get("forexcracked_reference_age_minutes"),
                "broker_executable": False},
            "why_now": row.get("why_now_evidence") or [],
            "news": row.get("news_headlines") or [],
            "macro_evidence": row.get("macro_directional_evidence") or [],
            "macro_contradictions": row.get("macro_dated_context") or [],
            "higher_timeframes": row.get("higher_timeframe_trend_context"),
            "adr_atr_room_and_chase_risk": row.get("range_context"),
            "invalidation_and_price_levels": row.get("daily_weekly_price_levels"),
            "timing_and_liquidity": row.get("session_liquidity_context"),
            "trade_execution_allowed": False,
        })

    intelligence = {
        "news_and_economic_catalysts": {
            "source": "fx_macro_news.json / fx_economic_calendar.json",
            "generated_at_utc": news.get("generated_at_utc"),
            "source_statuses": news.get("news_source_statuses"),
            "headlines": news.get("articles") or [],
            "matched_actuals": news.get("matched_actuals") or [],
            "calendar": calendar,
            "per_pair_upcoming_events": [
                {"pair": r["pair"], "events": r.get("economic_events_next_24h") or []}
                for r in all_pairs]},
        "global_yields_and_central_banks": {
            "source": "fx_macro_snapshot.json / fx_macro_raw.json",
            "macro_collected_at_utc": raw.get("collected_at_utc"),
            "nominal_yields": raw.get("bonds") or {},
            "policy_rates": raw.get("policy_rates") or {},
            "same_maturity_spreads": snapshot.get("same_maturity_yield_spreads") or {},
            "fetch_observed_deltas": snapshot.get("observed_fetch_deltas") or {},
            "historical_integrity": snapshot.get("historical_integrity"),
            "ois": raw.get("ois") or {"status": "UNAVAILABLE"}},
        "commodities_and_global_markets": {
            "source": "fx_macro_raw.json",
            "indices": raw.get("indices") or {},
            "noncrude_te_secondary": raw.get("noncrude_te_secondary") or {},
            "forexcracked": raw.get("forexcracked") or {},
            "crude_oilprice_only": raw.get("oilprice") or {},
            "vix": raw.get("vix_cboe_official_daily") or {},
            "feargreedmeter": raw.get("feargreedmeter") or {}},
        "institutional_and_retail_positioning": {
            "source": "fx_cftc_tff.json / fx_macro_raw.json / fx_unified_signals.json",
            "cftc_tff_weekly": cftc,
            "cme_futures": raw.get("cme_futures") or {"status": "UNAVAILABLE"},
            "retail_context_by_pair": [
                {"pair": r["pair"], "retail": r.get("retail_positioning_context")}
                for r in all_pairs]},
        "technical_analysis_and_levels": {
            "source": "fx_scan_dashboard.json / fx_unified_signals.json",
            "signal_timeframes": ["15m", "30m"],
            "context_timeframes": ["1H", "4H", "1D"],
            "excluded_from_signals": ["5m"],
            "per_pair": [
                {"pair": r["pair"], "technical": r.get("closed_candle_timeframe_context"),
                 "higher_timeframes": r.get("higher_timeframe_trend_context"),
                 "price_levels": r.get("daily_weekly_price_levels"),
                 "range_context": r.get("range_context"),
                 "cluster_context": r.get("currency_strength_cluster_context")}
                for r in all_pairs]},
        "source_integrity_and_unavailable_layers": {
            "source": "fx_integrated_audit.json / fx_unified_signals.json",
            "source_freshness_minutes": unified.get("source_freshness_minutes"),
            "macro_snapshot_used": unified.get("macro_snapshot_used"),
            "source_coverage": snapshot.get("source_coverage"),
            "fully_macro_verified": audit.get("fully_macro_verified", False),
            "missing_or_unverified": audit.get("unverified_layers") or [],
            "audit_sources": audit.get("sources") or {},
            "no_broker_verified_executable_spread": True},
    }
    extended = [
        {"pair": r.get("pair"), "stage": r.get("technical_stage")}
        for r in all_pairs
        if "EXTENDED" in str(r.get("technical_stage") or "").upper()]
    early = next((r for r in top if "EARLY" in str(r.get("technical_stage") or "").upper()), None)
    return {
        "currency_strength": strength,
        "best_five_trading_pairs": board,
        "five_detailed_trade_setups": setups,
        "complete_market_intelligence": intelligence,
        "all_11_pairs": all_pairs,
        "final_scan_conclusion": {
            "highest_ranked_technical_research_pair": top[0].get("pair") if top else None,
            "earliest_top_five_watch": early.get("pair") if early else None,
            "do_not_chase_extended": extended,
            "not_executable_broker_orders": True,
            "no_claim_of_full_live_macro_verification": not audit.get("fully_macro_verified", False),
            "source_rule": "Never fabricate missing prices, entries, stops, targets, yield deltas or confirmations",
        },
        "layout_contract": {
            "version": LAYOUT_VERSION,
            "fixed_order": PRESENTATION_ORDER,
            "default_locked_until_user_explicitly_changes_it": True,
            "preserve_full_11_pair_audit": True,
            "preserve_50_50_early_trend_rank": True,
            "data_as_of_utc": unified.get("generated_at_utc"),
            "no_orders_no_alerts": True,
        }
    }


def main():
    report = build_report(
        read("fx_unified_signals.json"), read("fx_scan_dashboard.json"),
        raw=read("fx_macro_raw.json"), news=read("fx_macro_news.json"),
        snapshot=read("fx_macro_snapshot.json"),
        calendar=read("fx_economic_calendar.json"),
        cftc=read("fx_cftc_tff.json"), audit=read("fx_integrated_audit.json"))
    Path("fx_scan_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"layout": LAYOUT_VERSION,
                      "strength_ranked": len(report["currency_strength"]["ranked_strongest_to_weakest"]),
                      "top_five": len(report["best_five_trading_pairs"]),
                      "all_11": len(report["all_11_pairs"]),
                      "order": PRESENTATION_ORDER}))


if __name__ == "__main__":
    main()
