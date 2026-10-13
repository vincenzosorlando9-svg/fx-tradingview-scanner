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


def _base_report(unified, dashboard, raw=None, news=None, snapshot=None,
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



# Definitive user-corrected contract: retain the detailed 15-layer MACRO-FIRST audit.
# The headline shows strength and published Top Five first for scan readability.
# Macro NEWS FIRST refers to the underlying investigation and numbered layers.
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from math import isfinite

LAYOUT_VERSION = "FOREX_MAIN_SIGNAL_15_LAYER_MACRO_FIRST_2026_10_13_V2"
LAYER_TITLES = [
    "REUTERS AND FXSTREET — MACRO NEWS FIRST",
    "ECONOMIC CALENDAR — ACTUALS, SURPRISES AND UPCOMING EVENTS",
    "CENTRAL BANKS AND OIS",
    "SOVEREIGN BONDS — 2Y/5Y/10Y/30Y",
    "COMMODITIES",
    "DXY, KOSPI, NIKKEI, CHINA AND SENTIMENT",
    "CFTC TFF — OFFICIAL WEEKLY POSITIONING",
    "CME FUTURES VOLUME AND OPEN INTEREST",
    "RETAIL POSITIONING",
    "CURRENCY-STRENGTH CLUSTERS",
    "ALL 11 — LATEST CLOSED 15m/30m SIGNALS",
    "1H/4H/DAILY CONTEXT",
    "ATR, ADR AND CONSOLIDATION",
    "CONDITIONAL TRIGGERS, INVALIDATION AND EXECUTION QUALITY",
    "HISTORICAL ACCOUNTABILITY",
]
PRESENTATION_ORDER = [
    "report_header",
    "top_five_published_ranking",
    "current_currency_strength",
    "critical_setups_omitted_from_top_five",
    "fifteen_layer_macro_first_audit",
    "full_15_layer_coverage_audit",
    "final_forex_main_signal",
    "layout_contract",
]
NY = ZoneInfo("America/New_York")
UTC = timezone.utc


def clock(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)
    except (TypeError, ValueError, OverflowError):
        return None


def et(value):
    dt = clock(value)
    return dt.astimezone(NY).strftime("%a %b %d, %Y %-I:%M:%S %p ET") if dt else "UNAVAILABLE"


def number(value, digits=1):
    return f"{value:.{digits}f}" if isinstance(value, (int, float)) and isfinite(value) else "MISSING"


def pip_multiplier(pair):
    return 100 if pair.endswith("JPY") else 10000


def candles_only_closed(data, pair, tf, collected):
    """Read only bars whose scheduled end precedes the upstream collection clock.

    The publisher's bars and clock are site-reported, NOT broker/exchange audited.
    Avoid using a forming bar, and never backdate these into published ranks.
    """
    fetched=clock(collected)
    frame=(((data.get("pairs") or {}).get(pair) or {}).get("tf") or {}).get(tf) or {}
    seconds={"M15":900,"M30":1800}.get(tf)
    times=frame.get("t") or []
    closes=frame.get("c") or []
    highs=frame.get("h") or []
    lows=frame.get("l") or []
    if fetched is None or seconds is None or len(times)!=len(closes):
        return {"status":"UNAVAILABLE_UNVERIFIED_CANDLE_TIMING"}
    index=None
    for i,t in enumerate(times):
        if isinstance(t, (int,float)) and t+seconds <= fetched.timestamp()+1:
            index=i
    if index is None or index<1:
        return {"status":"UNAVAILABLE_NO_TWO_COMPLETED_BARS"}
    end=datetime.fromtimestamp(times[index]+seconds, UTC)
    age=(fetched-end).total_seconds()/60
    if age< -1 or age > (22 if tf=="M15" else 37):
        return {"status":"UNAVAILABLE_STALE_LAST_CLOSED_CANDLE", "age_at_fetch_minutes":round(age,1)}
    try:
        current=float(closes[index])
        change=round((current-float(closes[index-1]))*pip_multiplier(pair),1)
    except (ValueError,TypeError):
        return {"status":"UNAVAILABLE_INVALID_CLOSE"}
    out={"status":"SITE_REPORTED_COMPLETED_CANDLE", "close":current,
         "change_pips":change, "closed_at_utc":end.isoformat(),
         "age_at_fetch_minutes":round(age,1),
         "source_collected_at_utc":collected,
         "upstream_independent_integrity_verified":False}
    if tf=="M15" and index>=23 and len(highs)>index and len(lows)>index:
        try:
            def width(start,stop):
                return round((max(float(x) for x in highs[start:stop]) -
                              min(float(x) for x in lows[start:stop])) *
                             pip_multiplier(pair),1)
            out["last_3h_range_pips"]=width(index-11,index+1)
            out["previous_3h_range_pips"]=width(index-23,index-11)
        except (TypeError,ValueError):
            pass
    return out


def latest_feed_view(volatility, unified):
    collected=volatility.get("collected_at_utc")
    fetch=clock(collected)
    published=clock(unified.get("generated_at_utc"))
    # Permit separately fetched newer candles with EXPLICIT time/source boundaries.
    if not fetch or not published or abs((fetch-published).total_seconds())>1800:
        return {
            "status":"UNAVAILABLE_STALE_OR_UNRELATED_VOLATILITY_FEED",
            "collected_at_utc":collected,
            "published_unified_generated_at_utc":unified.get("generated_at_utc"),
            "pairs":{}}
    rows={}
    for pair in PAIRS:
        m15=candles_only_closed(volatility,pair,"M15",collected)
        m30=candles_only_closed(volatility,pair,"M30",collected)
        usable=m15.get("status")=="SITE_REPORTED_COMPLETED_CANDLE" and m30.get("status")=="SITE_REPORTED_COMPLETED_CANDLE"
        rows[pair]={"15m":m15,"30m":m30,
                    "status":"TWO_CLOSED_CANDLES_OBSERVED" if usable else "PARTIAL_OR_UNAVAILABLE",
                    "site_reported_not_broker":True}
    return {
        "status":"SEPARATELY_OBSERVED_SITE_REPORTED_CLOSED_CANDLES",
        "collected_at_utc":collected,
        "published_unified_generated_at_utc":unified.get("generated_at_utc"),
        "ranking_predates_latest_observation":fetch>published,
        "observations_do_not_recalculate_published_scores":True,
        "pairs":rows}


def assess(row, latest, movement_pips=None):
    """Evidence-based updated assessment; NEVER rewrite original BUY/SELL history."""
    original=row.get("direction")
    stage=str(row.get("technical_stage") or "UNAVAILABLE")
    m15=latest.get("15m") or {}
    m30=latest.get("30m") or {}
    if latest.get("status")!="TWO_CLOSED_CANDLES_OBSERVED":
        return {"assessment":stage+" — LATEST CLOSED DATA UNAVAILABLE",
                "new_counter_rotation":False, "observed_direction":None,
                "published_direction":original}
    a,b=m15["change_pips"],m30["change_pips"]
    observed="BUY" if a>0 and b>0 else "SELL" if a<0 and b<0 else "MIXED"
    counter=observed in ("BUY","SELL") and observed!=original
    meaningful=abs(a)>=2.0 and abs(b)>=5.0
    if counter and meaningful:
        label=observed+" COUNTER-ROTATION WATCH — NOT A RECORDED "+observed+" EPISODE"
    elif counter:
        label=original+" EPISODE / OPPOSING PRESSURE — WATCH"
    elif observed=="MIXED":
        label=original+" EPISODE / MIXED CLOSED CANDLES — WAIT"
    elif isinstance(movement_pips,(int,float)) and movement_pips>=20:
        label=original+" EXTENDED EPISODE — DO NOT CHASE"
    elif isinstance(movement_pips,(int,float)) and movement_pips<=-8:
        label=original+" EPISODE — ADVERSE SINCE FIRST RECORD; RECHECK"
    elif abs(a)<1.5 and abs(b)>=5:
        label=original+" 30m PRESSURE / 15m DECELERATION — MONITOR"
    else:
        first=clock(row.get("signal_first_recorded_at_utc"))
        latest_candle=clock(m15.get("closed_at_utc"))
        genuinely_recent=bool(first and latest_candle and
                              -2 <= (latest_candle-first).total_seconds()/60 <= 30)
        early=(genuinely_recent and "EARLY" in stage and
               (not isinstance(movement_pips,(int,float)) or abs(movement_pips)<12))
        label=original+(" EARLY WATCH — NEWLY RECORDED" if early
                        else " CONTINUATION — MONITOR")
    return {"assessment":label,"new_counter_rotation":bool(counter and meaningful),
            "observed_direction":observed, "published_direction":original,
            "status":"PROVISIONAL_PUBLIC_CLOSED_CANDLES_NOT_NEW_UNIFIED_SIGNAL"}


def historic_accountability(row, latest, history):
    pair=row["pair"]
    active=(((history.get("pairs") or {}).get(pair) or {}).get("active") or {})
    direction=active.get("direction")
    first=active.get("first_observed_closed_15m_price")
    latest_price=(latest.get("15m") or {}).get("close")
    delta=None
    if direction in ("BUY","SELL") and isinstance(first,(int,float)) and isinstance(latest_price,(int,float)):
        side=1 if direction=="BUY" else -1
        delta=round((latest_price-first)*pip_multiplier(pair)*side,1)
    return {"pair":pair,"recorded_episode_direction":direction,
            "first_recorded_at_utc":active.get("first_observed_at_utc"),
            "first_recorded_price":first,"latest_completed_15m_price":latest_price,
            "pips_favorable_since_first_record":delta,
            "source":"RECORDED_HISTORY_VS_NEWEST_COMPLETED_PUBLIC_CANDLE",
            "not_trade_profit":True,
            "episode_is_active":bool(active),
            "no_retroactive_reversal":True}



def compact_stage(assessment):
    """Short *display* labels; preserve the full updated assessment elsewhere."""
    label=str(assessment or "UNAVAILABLE").upper()
    if "CHASE" in label or "EXTENDED" in label:
        return "CHASE"
    if "ADVERSE" in label or "RECHECK" in label:
        return "RISK"
    if "MIXED" in label or "WAIT" in label or "PAUSE" in label:
        return "WAIT"
    if "COUNTER" in label:
        return "COUNTER"
    if "CONFIRM" in label:
        return "CONF"
    if "CONTINUATION" in label or "MONITOR" in label:
        return "CONT"
    if "EARLY" in label:
        return "EARLY"
    return "WATCH"


def compact_side(direction):
    """Readable green/red symbols that work in Markdown without CSS support."""
    if direction=="BUY":
        return {"label":"BUY","color":"green","symbol":"🟢"}
    if direction in ("SELL","SHORT"):
        return {"label":"SHORT","color":"red","symbol":"🔴"}
    return {"label":"WAIT","color":"neutral","symbol":"⚪"}


def compact_strength(score):
    if not isinstance(score,(int,float)) or not isfinite(score):
        return {"label":"MISSING","color":"neutral","symbol":"⚪"}
    if score>0:
        return {"label":"STRONG","color":"green","symbol":"🟢"}
    if score<0:
        return {"label":"WEAK","color":"red","symbol":"🔴"}
    return {"label":"NEUTRAL","color":"neutral","symbol":"⚪"}


def keep_together(*items):
    """Nonbreaking spaces: one entire compact row, even on narrow mobile screens."""
    return "&nbsp;".join(str(item).replace(" ","&nbsp;") for item in items)


def compact_markdown_pair(row):
    side=compact_side(row.get("direction"))
    pair=row.get("pair") or "UNAVAILABLE"
    display_pair=pair[:3]+"/"+pair[3:] if len(pair)==6 else pair
    return keep_together("**"+str(row["published_rank"])+".**",
                         "**"+display_pair+"**",
                         side["symbol"],"**"+side["label"]+"**",
                         compact_stage(row.get("updated_assessment")),
                         "**"+number(row.get("published_score"),3)+"**")


def compact_markdown_currency(row):
    score=row.get("breadth_score")
    strength=compact_strength(score)
    signed=("+" if score>0 else "")+str(score) if isinstance(score,(int,float)) else "—"
    return keep_together("**"+str(row["rank"])+".**",
                         "**"+str(row["currency"])+"**",
                         strength["symbol"],"**"+strength["label"]+"**",
                         "**"+signed+"**")


def build_report(unified, dashboard, raw=None, news=None, snapshot=None,
                 calendar=None, cftc=None, audit=None, volatility=None,
                 history=None, retail=None, forexfactory=None, breaking=None):
    """Return the EXACT user-approved fifteen-layer structure in reading order."""
    legacy=_base_report(unified,dashboard,raw=raw,news=news,snapshot=snapshot,
                        calendar=calendar,cftc=cftc,audit=audit)
    raw,news,snapshot,calendar,cftc,audit=[x or {} for x in (raw,news,snapshot,calendar,cftc,audit)]
    volatility,history,retail,forexfactory=[x or {} for x in (volatility,history,retail,forexfactory)]
    breaking=breaking or {}
    policy_news=breaking.get("recent_headlines") or []
    prioritized_policy=[h for h in policy_news if h.get("priority")=="HIGH_POLICY_REACTION_CHECK"]
    all_pairs=unified["all_11"]
    current=latest_feed_view(volatility,unified)
    latest=current["pairs"]
    historical=[historic_accountability(r, latest.get(r["pair"],{}),history) for r in all_pairs]
    hist_by_pair={x["pair"]:x for x in historical}
    assessments={r["pair"]:assess(r,latest.get(r["pair"],{}),
                                hist_by_pair[r["pair"]]["pips_favorable_since_first_record"])
                 for r in all_pairs}
    rank=[]
    for i,r in enumerate(unified.get("top_five") or [],1):
        p=r["pair"]
        rank.append({**legacy["best_five_trading_pairs"][i-1],
                     "published_rank":i, "published_score":r.get("technical_research_rank_score"),
                     "updated_assessment":assessments[p]["assessment"],
                     "ranking_generated_at_utc":unified.get("generated_at_utc"),
                     "newer_candle_observation_collected_at_utc":current.get("collected_at_utc")
                         if current.get("status")=="SEPARATELY_OBSERVED_SITE_REPORTED_CLOSED_CANDLES" else None,
                     "published_ranking_preserved":True,
                     "score_is_not_trade_probability":True,
                     "breaking_policy_news":r.get("breaking_policy_news") or
                       {"status":"UNAVAILABLE_APPROVED_SOURCE","source_coverage_incomplete":True}})
    selected={r["pair"] for r in rank}
    omissions=[]
    for r in all_pairs:
        if r["pair"] in selected:
            continue
        view=latest.get(r["pair"],{})
        a=(view.get("15m") or {}).get("change_pips")
        b=(view.get("30m") or {}).get("change_pips")
        updated=assessments[r["pair"]]
        if not isinstance(a,(int,float)) or not isinstance(b,(int,float)):
            continue
        strength=round(abs(a)+abs(b),1)
        if updated["new_counter_rotation"] or (a*b>0 and abs(b)>=5):
            omissions.append({
                "pair":r["pair"],"published_direction":r.get("direction"),
                "current_closed_candle_assessment":updated["assessment"],
                "new_counter_rotation_not_in_recorded_history":updated["new_counter_rotation"],
                "15m_change_pips":a,"30m_change_pips":b,
                "latest_closed_15m_price":view["15m"].get("close"),
                "latest_closed_15m_at_utc":view["15m"].get("closed_at_utc"),
                "episode_movement_pips":hist_by_pair[r["pair"]]["pips_favorable_since_first_record"],
                "priority_score_for_display_only":strength,
                "not_added_to_published_top_five":True})
    omissions.sort(key=lambda x:(not x["new_counter_rotation_not_in_recorded_history"],
                                 -x["priority_score_for_display_only"]))
    # Above sorting is a separate displayed review priority, NOT the engine rank.
    news_articles=news.get("articles") or []
    matched=news.get("matched_actuals") or []
    observation=clock(current.get("collected_at_utc")) or clock(unified.get("generated_at_utc"))
    upcoming=[]
    for event in calendar.get("events") or []:
        when=clock(event.get("event_at_utc"))
        if observation and when and observation<=when<=observation+timedelta(days=1):
            upcoming.append(event)
    upcoming.sort(key=lambda e:e.get("event_at_utc") or "")
    bondrows=[]
    for currency,data in (raw.get("bonds") or {}).items():
        maturities=data.get("maturities") or {}
        bondrows.append({
            "country_or_currency":currency,"market_date":data.get("market_date"),
            "status":data.get("status"),
            "quote_timestamp_utc":data.get("quote_timestamp_utc"),
            "source":data.get("url"),
            **{tf: (maturities.get(tf) or {}).get("value_pct") for tf in ("2Y","5Y","10Y","30Y")}})
    policy=[{"currency":c,"rate_pct":d.get("policy_rate_pct"),
             "reference_date":d.get("reference_date") or d.get("reference_period"),
             "status":d.get("status"),"source":d.get("url")}
            for c,d in (raw.get("policy_rates") or {}).items()]
    cftc_rows=[{"currency":c, "dealers_net":v.get("dealer_net"),
                "asset_managers_net":v.get("asset_mgr_net"),
                "leveraged_funds_net":v.get("leveraged_net"),
                "historical_open_interest":v.get("open_interest_contracts")}
               for c,v in (cftc.get("currencies") or {}).items()]
    technical=[]
    htf=[]
    adr=[]
    triggers=[]
    jpy=[]
    for r in all_pairs:
        pair=r["pair"];v=latest.get(pair,{})
        m15=v.get("15m") or {}
        m30=v.get("30m") or {}
        updated=assessments[pair]
        technical.append({
            "pair":pair,"latest_15m_closed_price":m15.get("close"),
            "latest_15m_closed_at_utc":m15.get("closed_at_utc"),
            "15m_change_pips":m15.get("change_pips"),
            "latest_30m_closed_at_utc":m30.get("closed_at_utc"),
            "30m_change_pips":m30.get("change_pips"),
            "original_published_direction":r.get("direction"),
            "updated_directional_assessment":updated["assessment"],
            "counter_rotation_unrecorded":updated["new_counter_rotation"],
            "site_reported_data_not_broker":True})
        trend=r.get("higher_timeframe_trend_context") or {}
        structure=trend.get("closed_candle_structure") or {}
        ind=trend.get("EMA_context") or {}
        htf.append({"pair":pair,
                    "1H":structure.get("h1_bias"),
                    "4H":structure.get("h4_bias"),
                    "Daily":structure.get("daily_bias"),
                    "1H_EMA20":(ind.get("1H") or {}).get("ema20"),
                    "1H_EMA50":(ind.get("1H") or {}).get("ema50"),
                    "4H_EMA10":(ind.get("4H") or {}).get("ema10"),
                    "4H_EMA20":(ind.get("4H") or {}).get("ema20"),
                    "not_early_signal_veto":True})
        ranges=r.get("range_context") or {}
        adr.append({"pair":pair,
                    "observed_3h_width_pips":m15.get("last_3h_range_pips"),
                    "previous_3h_width_pips":m15.get("previous_3h_range_pips"),
                    "ADR20_pips":ranges.get("ADR20_pips"),
                    "NY17_used_pips":ranges.get("NY17_day_used_pips"),
                    "statistical_ADR_remaining_pips":ranges.get("ADR_remaining_reference_pips"),
                    "ADR_is_not_target":True,
                    "consolidation_origin_verified":False})
        triggers.append({"pair":pair,"original_direction":r.get("direction"),
                         "latest_provisional_assessment":updated["assessment"],
                         "conditional_research_trigger":"Require supporting fresh closed 15m/30m direction and structure; reject counter-rotation" if not updated["new_counter_rotation"] else "Require further closed-candle counter-rotation evidence; no historical SELL/BUY episode assumed",
                         "structural_invalidation":"Opposing confirmed closed 15m/30m structural rotation; specific level requires verified source",
                         "entry":r.get("entry"),"stop":r.get("stop"),
                         "tp1":r.get("tp1"),"tp2":r.get("tp2"),
                         "broker_executable":False})
        if pair.endswith("JPY"):
            jpy.append({"pair":pair,"15m_change_pips":m15.get("change_pips"),
                        "30m_change_pips":m30.get("change_pips"),
                        "site_reported":True})
    layer_data=[
        {"status":"PARTIAL_DATED_OR_BLOCKED",
         "breaking_news_priority_headlines":prioritized_policy,
         "breaking_news_source_statuses":breaking.get("source_statuses") or {},
         "breaking_news_source_coverage_gaps":breaking.get("source_coverage_gaps") or
               ["FAST_APPROVED_NEWS_UNAVAILABLE"],
         "breaking_news_generated_at_utc":breaking.get("generated_at_utc"),
         "breaking_news_cannot_assign_trade_direction":True,
         "headlines":news_articles,"news_source_statuses":news.get("news_source_statuses") or {},
         "verified_immediate_causal_reaction":False},
        {"status":"PARTIAL_PUBLISHER_ACTUAL_TIMES_UNVERIFIED",
         "released_events":matched,"upcoming_events_next_24h":upcoming,
         "calendar_source":calendar.get("source"),"calendar_collected_at_utc":calendar.get("collected_at_utc"),
         "post_release_immediate_reaction_verified":False},
        {"status":"PARTIAL_OIS_UNAVAILABLE",
         "published_policy_rate_references":policy,
         "ois":raw.get("ois") or {"status":"UNAVAILABLE"},
         "no_sovereign_yield_substitution_for_ois":True},
        {"status":"PARTIAL_DATE_ONLY_YIELDS",
         "nominal_yields":bondrows,"same_tenor_spreads":snapshot.get("same_maturity_yield_spreads") or {},
         "fetch_observed_deltas_not_exchange_timestamped":
             snapshot.get("observed_fetch_deltas") or {},
         "historical_integrity":snapshot.get("historical_integrity")},
        {"status":"PARTIAL_INDICATIVE_OR_DELAYED",
         "oil_oilprice_only":raw.get("oilprice") or {},
         "noncrude_forexcracked":(raw.get("forexcracked") or {}).get("non_crude") or {},
         "dated_te_noncrude":raw.get("noncrude_te_secondary") or {}},
        {"status":"PARTIAL_DATED_OR_INDICATIVE",
         "global_indices":raw.get("indices") or {},
         "vix_previous_close":raw.get("vix_cboe_official_daily") or {},
         "feargreedmeter":raw.get("feargreedmeter") or {},
         "usd_cnh":(raw.get("forexcracked") or {}).get("cross_risk") or {},
         "JPY_cross_closed_candles":jpy,
         "risk_off_alone_is_not_directional_FX_confirmation":True},
        {"status":cftc.get("status","UNAVAILABLE"),
         "report_date":cftc.get("report_date"),
         "currency_net_futures_only_contracts":cftc_rows,
         "prior_week_comparison":"UNAVAILABLE_UNLESS_EXPLICIT_PRIOR_REPORT_VALIDATED"},
        {"status":"MISSING_INDEPENDENT_CURRENT_CME_FUTURES_VOLUME_OI",
         "current_CME":raw.get("cme_futures") or {"status":"UNAVAILABLE"},
         "CFTC_historical_OI_must_not_be_labeled_live_CME":True},
        {"status":retail.get("status","UNAVAILABLE"),
         "myfxbook":retail,
         "forexfactory_market_pages":forexfactory,
         "never_guess_retail_long_short_percentages":True},
        {"status":legacy["currency_strength"]["status"],
         "technical_breadth":legacy["currency_strength"],
         "jpy_cluster":dashboard.get("early_rotation_jpy_cluster") or {},
         "not_independent_currency_strength_index":True},
        {"status":current["status"], "public_feed_collected_at_utc":current.get("collected_at_utc"),
         "closed_candle_timeframes":["15m","30m"],
         "pairs":technical,
         "old_rank_vs_new_observation_explicit":True},
        {"status":"CONTEXT_ONLY_NOT_EARLY_SIGNAL_VETO",
         "timeframes":["1H","4H","Daily"],
         "pairs":htf},
        {"status":"PARTIAL_STATISTICAL_NOT_EXECUTION_TARGET",
         "observed_three_hour_comparison":adr,
         "exact_consolidation_origin_counts_or_squeeze_signals":"UNAVAILABLE"},
        {"status":"MISSING_BROKER_EXECUTABLE_QUOTES",
         "per_pair_conditional_research_criteria":triggers,
         "broker_spreads_verified":False,
         "precise_entries_stops_and_targets_independently_verified":False},
        {"status":"VERIFIED_RECORDED_EPISODE_PLUS_SITE_REPORTED_CLOSED_CANDLE",
         "as_of_latest_observation":current.get("collected_at_utc"),
         "episode_accountability":historical,
         "false_positive_and_counter_rotation_cannot_be_retroactively_rewritten":True},
    ]
    layers=[{"layer":i+1,"title":LAYER_TITLES[i],**v} for i,v in enumerate(layer_data)]
    auditrows=[{"layer":i+1,"coverage":layer["title"],"status":layer["status"]}
               for i,layer in enumerate(layers)]
    strongest=legacy["currency_strength"]["strongest"]
    weakest=legacy["currency_strength"]["weakest"]
    status="PARTIAL — VERIFY PUBLISHER AND BROKER SOURCE LIMITATIONS"
    if omissions:
        one=omissions[0]
        status="PARTIAL — WATCH "+one["pair"]+" "+one["current_closed_candle_assessment"]
    summary={
        "highest_ranked_published_pair":rank[0]["pair"] if rank else None,
        "strongest_technical_breadth_currencies":strongest,
        "weakest_technical_breadth_currencies":weakest,
        "most_important_unranked_closed_candle_moves":omissions[:5],
        "top_five_published_rank_does_not_rewrite_newer_candle_assessments":True,
        "do_not_chase_or_wait":[r for r in technical if
                                ("WAIT" in r["updated_directional_assessment"] or
                                 "DO NOT CHASE" in r["updated_directional_assessment"])],
        "news_event_risk":upcoming[:10],
        "macro_evidence_status":"PARTIAL_NOT_FULLY_VERIFIED" if not audit.get("fully_macro_verified") else "INDEPENDENTLY_AUDITED",
        "no_executable_quotes_or_trades":True,
        "no_mobile_or_email_alerts":True}
    return {
        "report_header":{
            "title":"FOREX MAIN SIGNAL — 15-LAYER MACRO-FIRST AUDIT",
            "as_of_ET":et(current.get("collected_at_utc") if current.get("status")=="SEPARATELY_OBSERVED_SITE_REPORTED_CLOSED_CANDLES" else unified.get("generated_at_utc")),
            "status":status,"pair_count":11,
            "signal_candles":["15m","30m"],"api_keys_required":False,
            "technical_feed_collected_at_utc":current.get("collected_at_utc"),
            "unified_published_at_utc":unified.get("generated_at_utc"),
            "macro_collected_at_utc":raw.get("collected_at_utc"),
            "newer_observation_than_unified":current.get("ranking_predates_latest_observation"),
            "two_sources_not_automatically_synchronized":True,
            "breaking_policy_news_asof_utc":breaking.get("generated_at_utc"),
            "breaking_policy_news_current_status":
                "HIGH_POLICY_REACTION_CHECK" if prioritized_policy else
                "NO_CENTRAL_BANK_HEADLINE_VISIBLE_IN_APPROVED_FEEDS",
            "breaking_policy_news_gaps":breaking.get("source_coverage_gaps") or
                ["FAST_APPROVED_NEWS_UNAVAILABLE"],
            "scope":"FULL_15_LAYER_ANALYSIS_NOT_A_BROKER_EXECUTION_SIGNAL"},
        "top_five_published_ranking":{
            "heading":"BEST 5 TRADING PAIRS — PUBLISHED 50/50 TECHNICAL RANKING",
            "as_published_at_utc":unified.get("generated_at_utc"),
            "scores_not_probabilities":True,
            "updated_assessments_independent_from_published_scores":True,
            "rows":[{**r,"compact_side":compact_side(r.get("direction")),
                     "compact_stage":compact_stage(r.get("updated_assessment")),
                     "compact_one_line":compact_markdown_pair(r)}
                    for r in rank]},
        "current_currency_strength":{
            **legacy["currency_strength"],
            "top_five_compact":[{**r,"strength_style":compact_strength(r.get("breadth_score")),
                                "compact_one_line":compact_markdown_currency(r)}
                               for r in legacy["currency_strength"]["ranked_strongest_to_weakest"][:5]],
            "weaker_currencies_compact":[{**r,"strength_style":compact_strength(r.get("breadth_score")),
                                         "compact_one_line":compact_markdown_currency(r)}
                                        for r in legacy["currency_strength"]["ranked_strongest_to_weakest"][5:]],
        },
        "critical_setups_omitted_from_top_five":{
            "heading":"CRITICAL SETUPS OMITTED FROM TOP FIVE",
            "not_a_recalculated_ranking":True,
            "pairs":omissions},
        "fifteen_layer_macro_first_audit":layers,
        "full_15_layer_coverage_audit":auditrows,
        "final_forex_main_signal":summary,
        "layout_contract":{
            "version":LAYOUT_VERSION,
            "fixed_order":PRESENTATION_ORDER,
            "fixed_layer_titles":LAYER_TITLES,
            "default_locked_until_user_explicitly_changes_it":True,
            "no_wrap_compact_rows":True,
            "top_five_before_strength":True,
            "display_direction_buy_green_short_red":True,
            "top_strength_limit":5,
            "do_not_split_words_strong_short_buy":True,
            "do_not_simplify_to_six_sections":True,
            "no_unrecorded_retroactive_entries":True,
            "preserve_50pct_early_50pct_trend_ranking":True,
            "preserve_all_11_pairs":True,
            "no_M5_signal_inputs":True,
            "source_technical_generated_at_utc":unified.get("source_technical_generated_at_utc"),
            "source_unified_generated_at_utc":unified.get("generated_at_utc"),
            "source_latest_volatility_collected_at_utc":current.get("collected_at_utc"),
            "trades_executed":False,
            "notifications_sent":False}
    }


def cell(value):
    if isinstance(value, bool):
        return "YES" if value else "NO"
    if value is None or value=="":
        return "MISSING"
    if isinstance(value,float):
        return number(value, 2)
    return str(value).replace("|","/").replace("\n"," ")


def table_cell(col, row):
    value=row.get(col)
    if isinstance(value,float) and isfinite(value):
        # FX price precision is non-negotiable for correct pip accountability.
        if any(word in col.lower() for word in ("price","close","ema","level","bid","ask")):
            pair=row.get("pair") or ""
            return number(value, 3 if str(pair).endswith("JPY") else 5)
        if "score" in col.lower():
            return number(value, 3)
        return number(value, 1 if "pips" in col.lower() else 2)
    return cell(value)


def mdtable(columns, rows):
    if not rows:
        return "No verified rows available.\n"
    return "\n".join(["| "+" | ".join(columns)+" |",
                      "| "+" | ".join(["---"]*len(columns))+" |"]+
                     ["| "+" | ".join(table_cell(c,row) for c in columns)+" |" for row in rows])+"\n"


def render_markdown(report):
    """Readable full-length report matching the user's supplied section names."""
    h=report["report_header"]
    out=["# "+h["title"],"",
         h["as_of_ET"]+" | 11 pairs | Closed 15m/30m candles | No API keys",
         "","**OVERALL STATUS: "+h["status"]+"**","",
         "Latest separately fetched public technical feed: "+et(h["technical_feed_collected_at_utc"])+
         ". Authoritative unified rank: "+et(h["unified_published_at_utc"])+
         ". Macro fetch: "+et(h["macro_collected_at_utc"])+
         ". Published scores and newer candle assessments are deliberately distinguished.",
         "",
         "## 1. BEST 5 TRADING PAIRS — BUY / SHORT", ""]
    rank=report["top_five_published_ranking"]["rows"]
    out += ["**#   PAIR   SIGNAL   STAGE   SCORE**  ",
            *[r["compact_one_line"]+"  " for r in rank], "",
            "Green BUY / red SHORT; compact stage = early, confirming, continuation, wait or chase. Published scores are not probabilities. Detailed assessments appear in the full audit.",
            "",
            "## 2. CURRENCY STRENGTH — TOP 5", ""]
    cs=report["current_currency_strength"]
    out += ["**#   CCY   STRENGTH   SCORE**  ",
            *[r["compact_one_line"]+"  " for r in cs["top_five_compact"]], "",
            "**WEAKEST CURRENCIES**  ",
            *[r["compact_one_line"]+"  " for r in cs["weaker_currencies_compact"]], "",
            "Strongest: "+", ".join(cs["strongest"] or ["UNAVAILABLE"])+
            " | Weakest: "+", ".join(cs["weakest"] or ["UNAVAILABLE"]),
            "Scores are 11-pair technical breadth, NOT an independently verified real-time currency-strength feed.",
            "",
           "## CRITICAL SETUPS OMITTED FROM TOP FIVE",""]
    omissions=report["critical_setups_omitted_from_top_five"]["pairs"]
    out+= [mdtable(["pair","published_direction","current_closed_candle_assessment","15m_change_pips","30m_change_pips","episode_movement_pips"],omissions),
           "Counter-rotations are new candle evidence, NOT invented historical SELL/BUY episodes.",""]
    layers=report["fifteen_layer_macro_first_audit"]
    for layer in layers:
        n=layer["layer"]
        out+=["---","","## "+str(n)+". "+layer["title"],"",
              "**Coverage:** "+layer["status"],""]
        if n==1:
            out+=["**Breaking central-bank policy watch (five-minute target)**",
                  "Fast source collection: "+et(layer.get("breaking_news_generated_at_utc")),
                  "Source gaps: "+", ".join(layer["breaking_news_source_coverage_gaps"]),
                  "A missing approved news story never establishes that no policy headline occurred.",
                  mdtable(["published_at_utc","provider","title","affected_pairs","first_seen_at_utc","reaction_review"],
                          [{**h,"published_at_utc":et(h.get("published_at_utc")),
                            "first_seen_at_utc":et(h.get("first_seen_at_utc")),
                            "title":("[{}]({})".format(h.get("title",""),h.get("url"))
                                     if str(h.get("url","")).startswith("https://") else h.get("title")),
                            "affected_pairs":", ".join(h.get("affected_pairs") or []),
                            "reaction_review":("; ".join(
                                p+": "+str(v.get("status"))+
                                " ("+str(v.get("first_post_event_change_pips","?"))+"/"+
                                str(v.get("second_post_event_change_pips","?"))+"p), "+
                                ("RETROSPECTIVE" if v.get("retrospective_if_first_seen_after_first_candle") else "EARLY_CLOCK_CHECK")
                                for p,v in (h.get("price_reactions") or {}).items()
                                if p in ("AUDJPY","USDJPY","EURJPY","NZDJPY")) or "MISSING_VERIFIED_REACTION")}
                           for h in layer["breaking_news_priority_headlines"][:10]]),
                  "The publisher clock and first-seen time are DIFFERENT; RETROSPECTIVE means this was NOT detected ahead of the initial move.",
                  "The first two event-aligned 15m changes describe price observations, NOT causal proof or executable trading signals.", ""]
            sources=layer["news_source_statuses"]
            out+=["Sources: "+", ".join(k+": "+str(v) for k,v in sources.items())]
            rows=[{"published_at_utc":et(x.get("published_at_utc")),"provider":x.get("provider"),
                   "title":("[{}]({})".format(x.get("title",""),x.get("url")) if
                            str(x.get("url","")).startswith("https://") else x.get("title")),
                   "direction":x.get("direction")}
                  for x in layer["headlines"][:12]]
            out+=["",mdtable(["published_at_utc","provider","title","direction"],rows),
                  "Headlines alone do not demonstrate an independently verified immediate FX reaction."]
        elif n==2:
            rows=[{"currency":x.get("currency"),"title":x.get("title"),
                   "reported_actual":x.get("reported_actual"),"forecast":x.get("forecast"),
                   "previous":x.get("previous"),"status":x.get("status")}
                  for x in layer["released_events"]]
            out+=["**Released actuals**",mdtable(["currency","title","reported_actual","forecast","previous","status"],rows),
                  "**Upcoming events (next 24h)**",
                  mdtable(["event_at_et","currency","title","forecast","previous"],
                          [{**x,"event_at_et":et(x.get("event_at_utc"))} for x in layer["upcoming_events_next_24h"]]),
                  "Publisher-reported actuals are not equivalent to independently isolated event-price reactions."]
        elif n==3:
            out+=[mdtable(["currency","rate_pct","reference_date","status"],layer["published_policy_rate_references"]),
                  "OIS status: "+str((layer["ois"] or {}).get("status","UNAVAILABLE"))+
                  ". Do not substitute sovereign yields for market-implied OIS."]
        elif n==4:
            out+=[mdtable(["country_or_currency","2Y","5Y","10Y","30Y","market_date","status"],layer["nominal_yields"]),
                  "Same-maturity spread references and independently timed yield changes are preserved in the JSON layer; public-date yield references are not synchronized market ticks."]
        elif n==5:
            oil=layer["oil_oilprice_only"] or {}
            rows=[{"commodity":k,"value_usd_per_barrel":v.get("value_usd_per_barrel"),
                   "delay_minutes":v.get("delay_minutes"),"quote_timestamp_utc":v.get("quote_timestamp_utc")}
                  for k,v in (oil.get("commodities") or {}).items()]
            out+=["**Crude: OilPrice.com only**",mdtable(["commodity","value_usd_per_barrel","delay_minutes","quote_timestamp_utc"],rows)]
            nc=layer["noncrude_forexcracked"] or {}
            out+=["**Non-crude: ForexCracked indicative**",
                  mdtable(["commodity","value","status"],
                          [{"commodity":k,"value":v.get("value"),"status":v.get("status")} for k,v in nc.items()])]
        elif n==6:
            ix=layer["global_indices"]
            out+=[mdtable(["indicator","value","market_date","status"],
                         [{"indicator":k,"value":v.get("value"),
                           "market_date":v.get("market_date"),"status":v.get("status")}
                          for k,v in ix.items()]),
                  "**JPY-cluster check on completed 15m/30m candles:**",
                  mdtable(["pair","15m_change_pips","30m_change_pips"],
                          layer["JPY_cross_closed_candles"]),
                  "Risk-off context cannot override an unsynchronized FX cluster."]
        elif n==7:
            out+=["CFTC report date: "+cell(layer["report_date"]),
                  mdtable(["currency","dealers_net","asset_managers_net","leveraged_funds_net"],
                          layer["currency_net_futures_only_contracts"]),
                  "Historical futures-only positions; absent prior-week comparisons remain unavailable."]
        elif n==8:
            out+=["Current independently verified CME volume/OI: MISSING. Historical CFTC open interest is not live CME data."]
        elif n==9:
            out+=["Retail status: "+cell(layer["status"])+". Myfxbook and Forex Factory dynamic positioning must not be guessed."]
        elif n==10:
            cs=layer["technical_breadth"]
            out+=["Strongest: "+", ".join(cs["strongest"] or ["UNAVAILABLE"])+
                  " | Weakest: "+", ".join(cs["weakest"] or ["UNAVAILABLE"]),
                  mdtable(["rank","currency","breadth_score"],cs["ranked_strongest_to_weakest"])]
        elif n==11:
            out+=["Public technical feed collected: "+et(layer["public_feed_collected_at_utc"]),
                  mdtable(["pair","latest_15m_closed_price","latest_15m_closed_at_utc",
                           "15m_change_pips","30m_change_pips","original_published_direction",
                           "updated_directional_assessment"],layer["pairs"]),
                  "### WHY NOW — MOST IMPORTANT CHANGES",""]
            unique=[]
            for p in [x["pair"] for x in omissions[:3]]+[x["pair"] for x in rank[:3]]:
                if p not in unique: unique.append(p)
            table={x["pair"]:x for x in layer["pairs"]}
            archived={x["pair"]:x for x in report["fifteen_layer_macro_first_audit"][14]["episode_accountability"]}
            for p in unique:
                t=table.get(p,{})
                a=t.get("15m_change_pips");b=t.get("30m_change_pips")
                old=archived.get(p,{})
                row=next((x for x in report["fifteen_layer_macro_first_audit"][13]["per_pair_conditional_research_criteria"]
                          if x["pair"]==p),{})
                out += ["**"+p+" — "+str(t.get("updated_directional_assessment","UNAVAILABLE"))+"**",
                        "Latest completed 15m "+(number(a,1)+" pips" if a is not None else "MISSING")+
                        "; 30m "+(number(b,1)+" pips" if b is not None else "MISSING")+
                        ". Original published direction: "+cell(t.get("original_published_direction"))+
                        ". Recorded episode movement: "+cell(old.get("pips_favorable_since_first_record"))+
                        " pips (not realized P&L).",
                        "Evidence is public completed-candle structure only. Trigger: "+
                        cell(row.get("conditional_research_trigger"))+
                        ". Macro headlines/yields are separate, potentially conflicting context, not confirmed candle causality.",
                        ""]
        elif n==12:
            out+=[mdtable(["pair","1H","4H","Daily","1H_EMA20","1H_EMA50","4H_EMA10","4H_EMA20"],layer["pairs"]),
                  "These longer timeframes are contextual; they do not veto early completed 15m/30m rotations."]
        elif n==13:
            out+=[mdtable(["pair","observed_3h_width_pips","previous_3h_width_pips","ADR20_pips",
                          "NY17_used_pips","statistical_ADR_remaining_pips"],layer["observed_three_hour_comparison"]),
                  "Range widths are observed windows, not verified consolidation origins. ADR remaining is statistical capacity, not a target."]
        elif n==14:
            out+=[mdtable(["pair","original_direction","latest_provisional_assessment","conditional_research_trigger",
                          "structural_invalidation","entry","stop","tp1","tp2"],
                          layer["per_pair_conditional_research_criteria"]),
                  "No independently broker-verified executable quotes, stops, spreads or targets. Research only."]
        elif n==15:
            out+=[mdtable(["pair","recorded_episode_direction","first_recorded_at_utc",
                          "first_recorded_price","latest_completed_15m_price",
                          "pips_favorable_since_first_record"],layer["episode_accountability"]),
                  "Recorded observations do not imply realized P&L. Wrong-way episodes remain visible; counter-rotations are never retroactively invented."]
        out+=[""]
    out+=["---","","## FULL 15-LAYER COVERAGE AUDIT","",
          mdtable(["layer","coverage","status"],report["full_15_layer_coverage_audit"]),
          "---","",
          "## FINAL FOREX MAIN SIGNAL — "+h["as_of_ET"],"",
          "Strongest technical breadth: "+", ".join(report["final_forex_main_signal"]["strongest_technical_breadth_currencies"] or ["UNAVAILABLE"])+
          ". Weakest: "+", ".join(report["final_forex_main_signal"]["weakest_technical_breadth_currencies"] or ["UNAVAILABLE"])+".",
          "Highest published 50/50 research rank: "+cell(report["final_forex_main_signal"]["highest_ranked_published_pair"])+
          " (published score; separate from later candles).",
          ("Important omitted counter-rotations / accelerations: "+", ".join(x["pair"] for x in omissions[:5]))
          if omissions else "No independently qualifying omitted counter-rotation measured.",
          "Keep conditional BUY/SELL assessments separate from recorded active episodes. Newer candles may weaken or contradict the published board.",
          ("Upcoming calendar risk: "+", ".join(et(x.get("event_at_utc"))+" "+str(x.get("title")) for x in report["final_forex_main_signal"]["news_event_risk"][:5])) if report["final_forex_main_signal"]["news_event_risk"] else "Upcoming calendar events: UNAVAILABLE.",
          "",
          "**EXECUTION STATUS: RESEARCH WATCH ONLY.** Broker entries, stops, profit targets and spreads are not independently verified. No trades executed; no alerts generated.",
          "",
          "Sources: fx_unified_signals.json, fx_scan_dashboard.json, fx_volatility.json, fx_macro_raw.json, fx_macro_news.json, fx_economic_calendar.json, fx_cftc_tff.json, fx_signal_history.json, fx_integrated_audit.json.",
          ""]
    return "\n".join(out)


def main():
    report=build_report(read("fx_unified_signals.json"),read("fx_scan_dashboard.json"),
                        raw=read("fx_macro_raw.json"),news=read("fx_macro_news.json"),
                        snapshot=read("fx_macro_snapshot.json"),
                        calendar=read("fx_economic_calendar.json"),
                        cftc=read("fx_cftc_tff.json"),
                        audit=read("fx_integrated_audit.json"),
                        volatility=read("fx_volatility.json"),
                        history=read("fx_signal_history.json"),
                        retail=read("fx_retail_positioning.json"),
                        forexfactory=read("fx_forexfactory_markets.json"),
                        breaking=read("fx_news_priority.json"))
    Path("fx_scan_report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    Path("fx_scan_report.md").write_text(render_markdown(report),encoding="utf-8")
    print(json.dumps({"layout":LAYOUT_VERSION,"layers":len(report["fifteen_layer_macro_first_audit"]),
                      "published_top_five":len(report["top_five_published_ranking"]["rows"]),
                      "all_11":len(report["fifteen_layer_macro_first_audit"][10]["pairs"]),
                      "report_md":"fx_scan_report.md","order":PRESENTATION_ORDER}))


if __name__=="__main__":
    main()
