#!/usr/bin/env python3
"""Time-aware FX macro intelligence and technical signal fusion (no API keys).

Does not issue trades, mobile alerts or broker orders. A missing/stale macro
metric never vetoes closed-M15/M30 early direction. Every macro delta is
labelled as a difference observed between fetches, not a tick-timestamped move.
"""
import json
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_macro_collector import PAIRS

UTC = timezone.utc
CCY = ("USD", "EUR", "GBP", "JPY", "CAD", "AUD", "NZD")
RETENTION = 192                 # 2 days at nominal 15m cadence
WINDOWS_MIN = (15, 30, 60)
MAX_SAMPLE_DELAY_MIN = 45       # best-effort for GitHub cron delays
SOURCE_DATE_TOLERANCE_DAYS = 1  # daily pub references; no older-date intraday inference
UNVERIFIED = ("UNAVAILABLE", "STALE", "UNDATED", "FUTURE")
ISO = "%Y-%m-%d"

def read(path, fallback=None):
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
        return obj if isinstance(obj, dict) else (fallback if fallback is not None else {})
    except (ValueError, OSError):
        return fallback if fallback is not None else {}

def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                          encoding="utf-8")

def parse_dt(s):
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return dt.astimezone(UTC) if dt.tzinfo else None
    except (ValueError, TypeError):
        return None

def age_min(s, now):
    d = parse_dt(s)
    return (now - d).total_seconds() / 60 if d else None

def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

def metric(value, unit, source, label, market_date=None, source_observed_at_utc=None,
           retrieved_at_utc=None):
    if not valid_number(value):
        return None
    return {"v": value, "unit": unit, "source": source, "source_status": label,
            "market_date": market_date, "source_observed_at_utc": source_observed_at_utc,
            "retrieved_at_utc": retrieved_at_utc}

def observation_recent(m, now, max_date_days=SOURCE_DATE_TOLERANCE_DAYS):
    if not isinstance(m, dict) or not valid_number(m.get("v")):
        return False
    status = str(m.get("source_status") or "")
    if any(status.startswith(x) for x in UNVERIFIED):
        return False
    observed = parse_dt(m.get("source_observed_at_utc"))
    if observed is not None:
        minute_age = (now - observed).total_seconds() / 60
        return -2 <= minute_age <= 60
    d = m.get("market_date")
    if not d:
        return False
    try:
        days = (now.date() - datetime.strptime(d, ISO).date()).days
        return 0 <= days <= max_date_days
    except ValueError:
        return False

def normalize(raw):
    """Normalize observed source data while preserving missing dates and quote clocks."""
    result = {}
    for c, item in (raw.get("bonds") or {}).items():
        for tenor, quote in (item.get("maturities") or {}).items():
            if tenor not in ("2Y", "5Y", "10Y", "30Y"):
                continue
            key = "BOND:" + c + ":" + tenor
            result[key] = metric(
                quote.get("value_pct"), "percent_yield", item.get("url"),
                item.get("status"), market_date=item.get("market_date"),
                retrieved_at_utc=item.get("retrieved_at_utc"))
            if result[key]:
                result[key]["source_instrument"] = quote.get("source_row")
            # Public Trading Economics 'Day' is a percentage POINT change in
            # the published daily bond yield, not an intraday quote movement.
            published_day_change=quote.get("publisher_day_change_pp")
            if valid_number(published_day_change):
                result["BOND_DAY_CHANGE:" + c + ":" + tenor] = metric(
                    round(published_day_change*100,5), "publisher_daily_change_bps",
                    item.get("url"), item.get("status"),
                    market_date=item.get("market_date"),
                    retrieved_at_utc=item.get("retrieved_at_utc"))
    for c, item in (raw.get("policy_rates") or {}).items():
        m = metric(item.get("policy_rate_pct"), "percent_policy", item.get("url"),
                   item.get("status"), market_date=item.get("reference_date"),
                   retrieved_at_utc=item.get("retrieved_at_utc"))
        if m: result["POLICY:" + c] = m
    for symbol, item in (raw.get("indices") or {}).items():
        m = metric(item.get("value"), "index_points", item.get("url"),
                   item.get("status"), market_date=item.get("market_date"),
                   source_observed_at_utc=item.get("quote_timestamp_utc"),
                   retrieved_at_utc=item.get("retrieved_at_utc"))
        if m: result["INDEX:" + symbol] = m
        pct = metric(item.get("daily_change_pct"), "daily_percent_change", item.get("url"),
                     item.get("status"), market_date=item.get("market_date"),
                     retrieved_at_utc=item.get("retrieved_at_utc"))
        if pct: result["INDEX_DAILY_PCT:" + symbol] = pct
    fx = raw.get("forexcracked") or {}
    for pair, item in (fx.get("pairs") or {}).items():
        if pair not in PAIRS:
            continue
        for field in ("bid", "ask", "spread_pips"):
            value = item.get(field)
            m = metric(value, "indicative_quote" if field != "spread_pips" else "pips",
                       fx.get("url"), item.get("status"),
                       source_observed_at_utc=item.get("quote_timestamp_utc"),
                       retrieved_at_utc=fx.get("retrieved_at_utc"))
            if m: result["FX:" + pair + ":" + field.upper()] = m
    for symbol, item in (fx.get("non_crude") or {}).items():
        m = metric(item.get("value"), item.get("unit", "source_units"), fx.get("url"),
                   item.get("status"), source_observed_at_utc=item.get("quote_timestamp_utc"),
                   retrieved_at_utc=fx.get("retrieved_at_utc"))
        if m: result["COMMODITY:" + symbol] = m
    # CNH is a CHINA-RISK REFERENCE, never an extra trade pair.
    cnh=(fx.get("cross_risk") or {}).get("USD_CNH") or {}
    m=metric(cnh.get("bid"),"indicative_USD_per_CNH",fx.get("url"),
             cnh.get("status"),source_observed_at_utc=cnh.get("quote_timestamp_utc"),
             retrieved_at_utc=fx.get("retrieved_at_utc"))
    if m: result["CHINA:USD_CNH"]=m
    # Secondary public dated Trading Economics non-crude benchmark references.
    # ForexCracked is the preferred source when it has the instrument.
    # Never import WTI or Brent from a source other than OilPrice.com.
    te = raw.get("noncrude_te_secondary") or {}
    for symbol, item in (te.get("commodities") or {}).items():
        if symbol not in ("GOLD","SILVER","COPPER","IRON_ORE","COAL",
                          "EU_GAS","NATURAL_GAS"):
            continue
        key="COMMODITY:"+symbol
        if key in result:
            continue
        m=metric(item.get("value"),item.get("unit","unspecified"),
                 item.get("source_url") or te.get("url"),
                 "TE_SECONDARY_"+str(item.get("status") or "UNDATED"),
                 market_date=item.get("market_date"),
                 retrieved_at_utc=item.get("retrieved_at_utc") or te.get("retrieved_at_utc"))
        if m:
            m["source_priority"]="SECONDARY_FALLBACK_FOREXCRACKED_NOT_AVAILABLE"
            m["verified_intraday_quote"]=False
            result[key]=m
    oil = raw.get("oilprice") or {}
    for symbol, item in (oil.get("commodities") or {}).items():
        if symbol not in ("WTI", "BRENT"):
            continue
        # OilPrice.com explicitly delayed. Delay is not a publication timestamp.
        # OilPrice.com explicitly advertises delayed quotes. The latest
        # possible observation is fetch-time minus site delay; never claim an
        # exact publisher tick clock or a live broker reference.
        fetched=parse_dt(oil.get("retrieved_at_utc"))
        delay=item.get("delay_minutes")
        estimated=(fetched-timedelta(minutes=delay)).isoformat() if (
            fetched and isinstance(delay,int) and 0<=delay<=90) else None
        m = metric(item.get("value_usd_per_barrel"), "USD_per_barrel", oil.get("url"),
                   "DELAYED_APPROXIMATE_QUOTE_CLOCK" if estimated else item.get("status"),
                   source_observed_at_utc=estimated,
                   retrieved_at_utc=oil.get("retrieved_at_utc"))
        if m:
            m["delay_minutes"] = delay
            m["time_estimate_method"] = "LATEST_POSSIBLE_FETCH_MINUS_DECLARED_DELAY_NOT_REAL_QUOTE_TIME" if estimated else None
            result["COMMODITY:" + symbol] = m
    fg = raw.get("feargreedmeter") or {}
    m = metric(fg.get("index"), "sentiment_0_to_100", fg.get("url"),
               fg.get("status"), source_observed_at_utc=fg.get("quote_timestamp_utc"),
               retrieved_at_utc=fg.get("retrieved_at_utc"))
    if m: result["SENTIMENT:FEAR_GREED"] = m
    m = metric(fg.get("vix"), "VIX_points", fg.get("url"),
               fg.get("status"), source_observed_at_utc=fg.get("quote_timestamp_utc"),
               retrieved_at_utc=fg.get("retrieved_at_utc"))
    if m: result["INDEX:VIX_FGM"] = m
    return result

def snapshots_for_history(previous, now):
    history = previous.get("snapshots", [])
    if not isinstance(history, list):
        return []
    safe = []
    for item in history[-RETENTION:]:
        if not isinstance(item, dict) or not isinstance(item.get("metrics"), dict):
            continue
        when = parse_dt(item.get("at_utc"))
        if when and now - timedelta(days=4) <= when < now:
            safe.append(item)
    safe.sort(key=lambda x: x["at_utc"])
    return safe[-RETENTION:]

def derived_deltas(metrics, history, now):
    """Only compare matching metrics and sufficiently close *collection* windows."""
    output = {}
    for k, latest in metrics.items():
        windows = {}
        for window in WINDOWS_MIN:
            best, error = None, float("inf")
            for sample in history:
                observed = parse_dt(sample.get("at_utc"))
                if observed is None:
                    continue
                elapsed = (now - observed).total_seconds() / 60
                miss = abs(elapsed - window)
                tolerance = {15: 4, 30: 6, 60: 10}[window]
                if miss <= tolerance and miss < error:
                    old = sample.get("metrics", {}).get(k)
                    if old and valid_number(old.get("v")) and old.get("source") == latest.get("source"):
                        best, error = (old, observed, elapsed), miss
            if not best:
                windows[str(window)] = None
                continue
            old, observed, elapsed = best
            if (not observation_recent(latest, now) or
                not observation_recent(old, observed) or
                (latest.get("source_status") != old.get("source_status")) or
                (latest.get("unit") != old.get("unit")) or
                (latest.get("source_instrument") != old.get("source_instrument")) or
                (latest.get("market_date") != old.get("market_date") and
                 latest.get("source_observed_at_utc") is None)):
                windows[str(window)] = None
                continue
            delta = latest["v"] - old["v"]
            unit = latest["unit"]
            if unit == "percent_yield":
                delta = delta * 100
                unit = "basis_points"
                # Extreme sampled shifts need independently timestamped checks.
                if abs(delta) > {15: 20, 30: 30, 60: 45}[window]:
                    windows[str(window)] = None
                    continue
            elif unit in ("index_points", "USD_per_barrel", "source_units", "SOURCE_QUOTE_UNITS"):
                if not old["v"]:
                    windows[str(window)] = None
                    continue
                delta = (delta / abs(old["v"])) * 100
                unit = "percent_change"
            elif unit in ("indicative_quote",):
                pip = .01 if k.endswith(("JPY:BID", "JPY:ASK")) else .0001
                delta = delta / pip
                unit = "pips"
            windows[str(window)] = {
                "change": round(delta, 5), "unit": unit,
                "minutes_between_fetches": round(elapsed, 1),
                "first_retrieved_at_utc": observed.isoformat(),
                "last_retrieved_at_utc": now.isoformat(),
                "timing_evidence": "SAMPLED_FETCH_DIFFERENCE_NOT_VERIFIED_PUBLISHER_MOVE_TIME",
            }
        output[k] = windows
    return output

def rate_spreads(metrics, deltas, now):
    spreads = {}
    # Same-maturity spreads only; German yields proxy euro rates, not an ECB OIS.
    groups = ("USD", "EUR", "GBP", "JPY", "CAD", "AUD", "NZD", "FR", "IT")
    for base in groups:
        for quote in groups:
            if base == quote:
                continue
            for tenor in ("2Y", "10Y"):
                k1, k2 = "BOND:" + base + ":" + tenor, "BOND:" + quote + ":" + tenor
                a, b = metrics.get(k1), metrics.get(k2)
                if not a or not b or not observation_recent(a, now) or not observation_recent(b, now):
                    continue
                if a.get("market_date") != b.get("market_date"):
                    continue
                spread = {"level_bps": round((a["v"] - b["v"]) * 100, 2),
                          "market_date": a.get("market_date"),
                          "tenor": tenor, "source": "Trading Economics public government bonds",
                          "clock_accuracy": "DATE_ONLY_NOT_INTRADAY_QUOTE"}
                daily_a=metrics.get("BOND_DAY_CHANGE:" + base + ":" + tenor)
                daily_b=metrics.get("BOND_DAY_CHANGE:" + quote + ":" + tenor)
                if daily_a and daily_b and observation_recent(daily_a, now) and observation_recent(daily_b,now):
                    spread["publisher_daily_spread_change_bps"]=round(daily_a["v"]-daily_b["v"],3)
                    spread["publisher_daily_change_clock"]="PUBLISHED_DAY_CLOSE_REFERENCE_NOT_15M_30M"
                for window in WINDOWS_MIN:
                    x = (deltas.get(k1) or {}).get(str(window))
                    y = (deltas.get(k2) or {}).get(str(window))
                    if x and y and x["unit"] == y["unit"] == "basis_points":
                        spread["observed_change_" + str(window) + "m_bps"] = round(
                            x["change"] - y["change"], 2)
                        spread["change_timing"] = "SAMPLED_FETCH_DIFFERENCE_NOT_EXCHANGE_TIMED"
                spreads[base + "/" + quote + ":" + tenor] = spread
    return spreads

def evidence_for_pair(pair, spreads, deltas, metrics, now):
    """Directional hints are corroboration only, never a requirement to issue an early watch."""
    base, quote = pair[:3], pair[3:]
    evidence, risk = [], []
    def add(name, direction, change, unit, detail, status):
        evidence.append({"driver": name, "favors": direction, "change": change,
                         "unit": unit, "detail": detail, "quality": status})
    for tenor in ("2Y", "10Y"):
        r = spreads.get(base + "/" + quote + ":" + tenor)
        if not r:
            continue
        value = next((r.get("observed_change_" + str(w) + "m_bps")
                      for w in (30, 60, 15) if r.get("observed_change_" + str(w) + "m_bps") is not None), None)
        if value is not None and abs(value) >= (1.0 if tenor == "2Y" else 1.5):
            add("YIELD_SPREAD_" + tenor, "BUY" if value > 0 else "SELL", value, "basis_points",
                "Relative " + base + "/" + quote + " yield changes over matching observed sample windows",
                "INDICATIVE_SAMPLED_NOT_QUOTE_TIMESTAMPED")
        risk.append({"driver": "YIELD_SPREAD_" + tenor,
                     "level_bps": r["level_bps"], "market_date": r["market_date"],
                     "published_daily_spread_change_bps": r.get("publisher_daily_spread_change_bps"),
                     "published_daily_change_status":r.get("publisher_daily_change_clock",
                                                           "UNAVAILABLE")})
    # Crude, gold and risk movements require two separate observed page values.
    def sampled(name, minimum=0.3):
        key = ("COMMODITY:" if name in ("WTI", "BRENT", "GOLD", "COPPER", "IRON_ORE") else
               "INDEX:" if name in ("DXY", "NIKKEI", "KOSPI", "CHINA_EQUITIES") else
               "SENTIMENT:") + name
        obj = metrics.get(key)
        if obj is None:
            return None
        # For date-only indices, only use changed same-date observations.
        if not observation_recent(obj, now):
            return None
        for window in (30, 60, 15):
            d = (deltas.get(key) or {}).get(str(window))
            if d and abs(d["change"]) >= minimum:
                return d
        return None
    # OilPrice.com has no quote timestamp: observed changes remain downgraded, not broker/live.
    for symbol in ("WTI", "BRENT"):
        x = sampled(symbol, .5)
        if x and ("CAD" in pair):
            preferred = ("BUY" if (x["change"] > 0) == (base == "CAD") else "SELL")
            add(symbol + "_OIL", preferred, x["change"], x["unit"],
                "Oil/CAD co-movement hypothesis, not causation",
                "LOW_CONFIDENCE_DELAYED_CRUDE_REFERENCE")
    for name, currency, threshold in (("COPPER", "AUD", .45), ("IRON_ORE", "AUD", .7)):
        x = sampled(name, threshold)
        if x and currency in pair:
            preferred = "BUY" if (x["change"] > 0) == (base == currency) else "SELL"
            add(name + "_COMMODITY", preferred, x["change"], x["unit"],
                "Commodity/" + currency + " correlation hypothesis", "LOW_CONFIDENCE_INDICATIVE")
    if "USD" in pair:
        x = sampled("DXY", .15)
        if x:
            preferred = "BUY" if (x["change"] > 0) == (base == "USD") else "SELL"
            add("DXY_BREADTH", preferred, x["change"], x["unit"],
                "DXY includes EUR-heavy weighting; not independent USD FX proof",
                "LOW_CONFIDENCE_REFERENCE")
    for symbol in ("KOSPI", "NIKKEI", "CHINA_EQUITIES"):
        ix = metrics.get("INDEX:" + symbol)
        if ix and observation_recent(ix, now):
            risk.append({"driver": symbol + "_DATED_CONTEXT", "value": ix["v"],
                         "market_date": ix.get("market_date"),
                         "note": "Daily context only; no direct BUY/SELL vote"})
    yuan=metrics.get("CHINA:USD_CNH")
    if yuan and observation_recent(yuan,now) and ("AUD" in pair or "NZD" in pair):
        change=next(((deltas.get("CHINA:USD_CNH") or {}).get(str(w))
                     for w in (30,60,15) if (deltas.get("CHINA:USD_CNH") or {}).get(str(w))),
                    None)
        risk.append({"driver":"USD_CNH_CHINA_REFERENCE",
                     "indicative_level":yuan["v"],
                     "sampled_change":change,
                     "note":"CNH proxy for AUD/NZD risk context; NOT an automatic directional vote or confirmed source of FX move"})
    for symbol in ("FEAR_GREED",):
        x = sampled(symbol, 5)
        if x:
            risk.append({"driver": "FEAR_GREED_SAMPLED_CHANGE",
                         "change": x["change"], "note": "General sentiment context, not a direction vote"})
    return evidence, risk

def news_context(raw, actuals, now):
    articles = []
    seen = set()
    for provider, r in (raw.get("news_sources") or {}).items():
        for item in r.get("articles", []):
            p = parse_dt(item.get("published_at_utc"))
            if not p or not now - timedelta(hours=48) <= p <= now + timedelta(minutes=3):
                continue
            url = item.get("url")
            if not url or url in seen:
                continue
            seen.add(url)
            articles.append({**item, "provider": provider})
    articles.sort(key=lambda i: i["published_at_utc"], reverse=True)
    results = []
    for row in (actuals.get("actuals") or []):
        t = parse_dt(row.get("scheduled_at_utc"))
        if t and now - timedelta(hours=48) <= t <= now and row.get("reported_actual"):
            results.append(row)
    return {"generated_at_utc": now.isoformat(),
            "news_source_statuses": {k: v.get("status") for k,v in (raw.get("news_sources") or {}).items()},
            "articles": articles[:70],
            "actuals_status": actuals.get("status", "UNAVAILABLE"),
            "matched_actuals": results[:100],
            "note": "Headlines are not assumed directional; Forex Factory actuals are publisher-reported, not independently confirmed official releases"}

def calendar_events(calendar, pair, now):
    future, past = [], []
    for row in (calendar.get("pairs") or {}).get(pair, []):
        when = parse_dt(row.get("event_at_utc"))
        if not when:
            continue
        m = (when - now).total_seconds() / 60
        x = {"currency": row.get("currency"), "title": row.get("title"),
             "scheduled_at_utc": when.isoformat(), "minutes_until": round(m, 1),
             "impact": row.get("impact"), "forecast": row.get("forecast"),
             "previous": row.get("previous")}
        if 0 <= m <= 1440:
            future.append(x)
        elif -120 <= m < 0:
            past.append(x)
    return sorted(future, key=lambda x:x["scheduled_at_utc"]), sorted(past, key=lambda x:x["scheduled_at_utc"], reverse=True)

def build_pairs(dashboard, early, calendar, news, spreads, deltas, metrics, cftc, raw, now, retail=None):
    dash_by_pair = {p.get("pair"): p for p in dashboard.get("pairs", []) if isinstance(p, dict)}
    early_by_pair = {p.get("pair"): p for p in early.get("pairs", []) if isinstance(p, dict)}
    retail = retail or {}
    retail_at = age_min(retail.get("collected_at_utc"), now)
    retail_ok = retail_at is not None and -2 <= retail_at <= 90
    pairs = []
    for pair in PAIRS:
        t = dash_by_pair.get(pair, {})
        e = early_by_pair.get(pair, {})
        direction = t.get("canonical_direction") or t.get("direction") or e.get("direction") or "NONE"
        if direction not in ("BUY", "SELL"):
            direction = "NONE"
        stage = t.get("canonical_stage") or e.get("stage") or t.get("stage") or "UNAVAILABLE"
        first_price = t.get("last_closed_15m_price")
        tf = (t.get("timeframes") or {})
        recent_15 = age_min((tf.get("15m") or {}).get("last_closed_utc"), now)
        recent_30 = age_min((tf.get("30m") or {}).get("last_closed_utc"), now)
        technical_ok = (bool(t.get("source_valid")) and
                        recent_15 is not None and 0 <= recent_15 <= 40 and
                        recent_30 is not None and 0 <= recent_30 <= 65 and
                        valid_number(first_price))
        evid, context = evidence_for_pair(pair, spreads, deltas, metrics, now)
        valid_directional = [x for x in evid if x.get("quality") not in ("UNAVAILABLE",)]
        buys, sells = [x for x in valid_directional if x["favors"] == "BUY"], [x for x in valid_directional if x["favors"] == "SELL"]
        if not valid_directional:
            macro_alignment = "UNKNOWN"
        elif buys and sells:
            macro_alignment = "MIXED"
        else:
            macro_direction = "BUY" if buys else "SELL"
            macro_alignment = "SUPPORTIVE" if macro_direction == direction and direction != "NONE" else "CONTRADICTORY"
        future, recent = calendar_events(calendar, pair, now)
        current_soon = [x for x in future if x["minutes_until"] <= 120]
        news_for_pair = [x for x in news.get("articles", []) if (
            pair[:3] in x.get("currencies", []) or pair[3:] in x.get("currencies", [])
            or ("CNY" in x.get("currencies", []) and
                ("AUD" in pair or "NZD" in pair)))][:10]
        actuals = [x for x in news.get("matched_actuals", []) if
                   x.get("currency") in (pair[:3], pair[3:]) or
                   x.get("currency") == "CNY" and ("AUD" in pair or "NZD" in pair)]
        cftc_context = {c: (cftc.get("currencies") or {}).get(c) for c in (pair[:3], pair[3:])}
        retail_raw = (retail.get("pairs") or {}).get(pair,{}) if retail_ok else {}
        retail_context = {
            "source": "Myfxbook public community outlook",
            "status": retail_raw.get("status", "UNAVAILABLE"),
            "long_pct": retail_raw.get("long_pct"),
            "short_pct": retail_raw.get("short_pct"),
            "retrieved_at_utc": retail_raw.get("retrieved_at_utc"),
            "publisher_delay_min": 60,
            "time_reference": "DELAYED_RETAIL_SAMPLE_NO_VERIFIED_TICK_TIME",
            "directional_vote": False}
        score_early = e.get("early_opportunity_score_50pct")
        score_trend = e.get("trend_strength_score_50pct")
        candidate_score = e.get("research_rank_score")
        if not valid_number(candidate_score):
            candidate_score = 0.5 * (score_early + score_trend) if (
                valid_number(score_early) and valid_number(score_trend)) else 0
        why = []
        pressure = e.get("pressure_evidence") or {}
        if pressure.get("evidence"):
            why.append({"type": "TECHNICAL", "observations": pressure["evidence"],
                        "asof_utc": e.get("latest_closed_m15_utc"),
                        "timeframes": ["15m", "30m"]})
        for x in valid_directional:
            why.append({"type": "MACRO_INDICATIVE", "driver": x["driver"],
                        "direction": x["favors"], "change": x["change"],
                        "unit": x["unit"], "quality": x["quality"]})
        if not why:
            why.append({"type": "UNVERIFIED", "note": "No sufficiently current corroborating evidence"})
        ff = raw.get("forexcracked", {})
        indicative = (ff.get("pairs") or {}).get(pair, {})
        quote_clock = parse_dt(indicative.get("quote_timestamp_utc"))
        clock_min = (now - quote_clock).total_seconds()/60 if quote_clock else None
        reference = {"last_closed_15m": first_price,
                     "closed_at_utc": (tf.get("15m") or {}).get("last_closed_utc"),
                     "forexcracked_indicative_bid": indicative.get("bid"),
                     "forexcracked_indicative_ask": indicative.get("ask"),
                     "forexcracked_reference_age_minutes": round(clock_min, 1) if clock_min is not None else None,
                     "broker_bid_ask_verified": False,
                     "spread_source": "FOREXCRACKED_INDICATIVE_NOT_EXECUTION" if indicative else "UNAVAILABLE"}
        score = round(float(candidate_score), 4)
        pairs.append({
            "pair": pair, "direction": direction if technical_ok else "DATA_STALE",
            "technical_direction_last_known": direction,
            "technical_stage": stage, "technical_15m30m_fresh": technical_ok,
            "latest_closed_m15_age_minutes": round(recent_15, 1) if recent_15 is not None else None,
            "latest_closed_m30_age_minutes": round(recent_30, 1) if recent_30 is not None else None,
            "possible_opposite_rotation": e.get("possible_opposite_rotation"),
            "early_opportunity_score_50pct": score_early,
            "trend_strength_score_50pct": score_trend,
            "technical_research_rank_score": score,
            "macro_alignment": macro_alignment, "macro_directional_evidence": valid_directional,
            "macro_dated_context": context, "news_headlines": news_for_pair,
            "recent_publisher_actuals": actuals[:10],
            "economic_events_next_24h": future, "events_previous_2h": recent,
            "event_within_120_minutes": bool(current_soon),
            "CFTC_weekly_futures_only_context": cftc_context,
            "retail_positioning_context": retail_context,
            "reference_prices": reference, "why_now_evidence": why,
            "fx_source_differences_not_executable": True,
            "trade_execution_allowed": False, "entry": None, "stop": None,
            "tp1": None, "tp2": None,
            "signal_classification": "EARLY_PROVISIONAL_WATCH" if (
                technical_ok and direction in ("BUY", "SELL") and "EARLY" in stage.upper()) else (
                "DIRECTIONAL_WATCH" if technical_ok and direction in ("BUY", "SELL") else "NO_FRESH_TECHNICAL_WATCH"),
            "signal_first_recorded_at_utc": ((t.get("signal_history") or {}).get("first_observed_at_utc")),
            "no_5m_signal_inputs": True})
    pairs.sort(key=lambda p: (p["technical_15m30m_fresh"], p["technical_research_rank_score"]), reverse=True)
    for i, row in enumerate(pairs, 1):
        row["research_rank"] = i
    return pairs

def main():
    now = datetime.now(UTC)
    raw = read("fx_macro_raw.json")
    actuals = read("fx_economic_actuals.json")
    cal = read("fx_economic_calendar.json")
    cftc = read("fx_cftc_tff.json")
    retail = read("fx_retail_positioning.json")
    dash = read("fx_scan_dashboard.json")
    early = read("fx_early_rotation.json")
    history_data = read("fx_macro_history.json")
    history = snapshots_for_history(history_data, now)
    raw_age = age_min(raw.get("collected_at_utc"), now)
    if raw_age is None or not -2 <= raw_age <= MAX_SAMPLE_DELAY_MIN:
        # No stale-looking snapshot may be relabeled "fresh" because this engine runs.
        raw = {"collected_at_utc": raw.get("collected_at_utc"),
               "status": "UNAVAILABLE_FRESH_MACRO_COLLECTION"}
    metrics = {k: v for k, v in normalize(raw).items() if v is not None}
    deltas = derived_deltas(metrics, history, now)
    spreads = rate_spreads(metrics, deltas, now)
    news = news_context(raw, actuals, now)
    observed = {"at_utc": now.isoformat(), "metrics": metrics}
    last = parse_dt(history[-1].get("at_utc")) if history else None
    # Skip push-trigger bursts; regular collection is roughly 15 minutes.
    if not last or (now - last).total_seconds() >= 9 * 60:
        history.append(observed)
    history = history[-RETENTION:]
    write("fx_macro_history.json", {"schema_version": 1,
          "updated_at_utc": now.isoformat(), "snapshots": history})
    coverage = {
        "bond_tenors": {c: {t: bool(metrics.get("BOND:" + c + ":" + t)) for t in ("2Y","5Y","10Y","30Y")}
                        for c in ("USD","EUR","GBP","JPY","CAD","AUD","NZD","FR","IT")},
        "yield_observations_count": sum(k.startswith("BOND:") for k in metrics),
        "policy_observations_count": sum(k.startswith("POLICY:") for k in metrics),
        "index_observations_count": sum(k.startswith("INDEX:") for k in metrics),
        "commodity_observations_count": sum(k.startswith("COMMODITY:") for k in metrics),
        "TE_secondary_noncrude_status": raw.get("noncrude_te_secondary",{}).get("status","UNAVAILABLE"),
        "fx_pairs_indicative_count": len(raw.get("forexcracked", {}).get("pairs", {})),
        "USDCNH_china_indicative_context": "PRESENT" if "CHINA:USD_CNH" in metrics else "UNAVAILABLE",
        "CFTC_report": cftc.get("status", "UNAVAILABLE"),
        "retail_public_delayed_status": (read("fx_retail_sentiment.json").get("status","UNAVAILABLE")),
        "retail_sample_status": retail.get("status", "UNAVAILABLE"),
        "retail_pairs_delayed": sum(x.get("status") == "PUBLISHED_RETAIL_SAMPLE_DELAYED_60_MIN"
                                     for x in (retail.get("pairs") or {}).values()),
        "CME_daily_open_interest": "UNAVAILABLE_INDEPENDENT_CME_SOURCE",
        "forexfactory_actuals": actuals.get("status", "UNAVAILABLE"),
        "broker_executable_bid_ask": "UNAVAILABLE_NO_BROKER_ACCESS",
        "OIS_rate_expectations": "UNAVAILABLE_NO_VERIFIED_OIS",
        "sentiment": raw.get("feargreedmeter", {}).get("status", "UNAVAILABLE"),
        "Reuters": raw.get("news_sources", {}).get("Reuters_currency_page", {}).get("status", "UNAVAILABLE"),
        "FXStreet": raw.get("news_sources", {}).get("FXStreet_RSS", {}).get("status", "UNAVAILABLE"),
        "sources_have_true_intraday_yield_quote_timestamps": False,
        "CNN": "EXCLUDED_AT_USER_REQUEST", "options": "REMOVED_AT_USER_REQUEST",
    }
    snapshot = {"schema_version": 1, "generated_at_utc": now.isoformat(),
        "raw_collected_at_utc": raw.get("collected_at_utc"),
        "metrics": metrics, "observed_fetch_deltas": deltas,
        "same_maturity_yield_spreads": spreads,
        "source_coverage": coverage,
        "timing_note": "Fetched changes are not necessarily actual 15m/30m market changes; source quote timestamps must be validated.",
        "real_time_status": "PUBLIC_DATE_OR_DELAYED_REFERENCES_NOT_VERIFIED_LIVE"}
    write("fx_macro_snapshot.json", snapshot)
    write("fx_macro_news.json", news)
    rows = build_pairs(dash, early, cal, news, spreads, deltas, metrics, cftc, raw, now,
                       retail=retail)
    retail=read("fx_retail_sentiment.json")
    retail_age=age_min(retail.get("collected_at_utc"), now)
    retail_fresh=(retail_age is not None and -2 <= retail_age <= 70)
    for row in rows:
        ref=(retail.get("pairs") or {}).get(row["pair"]) if retail_fresh else None
        row["retail_positioning"]=ref or {"status":"UNAVAILABLE_OR_UNVERIFIED_DELAYED_RETAIL"}
        row["retail_data_alters_direction"]=False
    range_data=read("fx_range_context.json")
    range_age=age_min(range_data.get("generated_at_utc"), now)
    range_fresh=(range_age is not None and 0<=range_age<=45 and
                 range_data.get("status")=="OBSERVED_REFERENCE_CONTEXT")
    for row in rows:
        row["range_context"]=(range_data.get("pairs") or {}).get(row["pair"]) if range_fresh else {
            "status":"UNAVAILABLE_STALE_OR_MISSING_RANGE_REFERENCE"}
        row["range_data_is_directional_signal"]=False
        row["session_liquidity_context"]={
            "upcoming_2h_event":row["event_within_120_minutes"],
            "holiday_on_calendar":any(str(x.get("impact","")).lower()=="holiday" for x in
                row.get("economic_events_next_24h",[])),
            "broker_spread_verified":False,
            "liquidity_interpretation":"SCHEDULED_SESSION_AND_EVENT_CONTEXT_NOT_MEASURED_ORDERBOOK"}
    signal = {"schema_version": 1, "generated_at_utc": now.isoformat(),
        "source_technical_generated_at_utc": dash.get("generated_at_utc"),
        "source_early_rotation_generated_at_utc": early.get("generated_at_utc"),
        "source_macro_collected_at_utc": raw.get("collected_at_utc"),
        "scope": "11_PAIR_RESEARCH_ONLY_NO_ORDERS_OR_ALERTS",
        "signals_from": "CLOSED_15M_30M_ONLY",
        "context_from": "1H_4H_DAILY_AND_MACRO",
        "macro_missing_does_not_veto_early_technical_direction": True,
        "ranking_policy": "50pct_early_opportunity_plus_50pct_trend_strength; macro alignment displayed independently",
        "no_mobile_alerts": True, "real_broker_spread_verified": False,
        "top_five": rows[:5], "all_11": rows, "pair_count": len(rows),
        "integrity": coverage}
    # The 5-minute technical workflow is the EXCLUSIVE publisher of the
    # unified signal board. Macro collection computes metrics and 15m changes
    # independently so simultaneous 5m/15m commits cannot conflict.
    if os.environ.get("FX_MACRO_NO_UNIFIED_WRITE") != "1":
        write("fx_unified_signals.json", signal)
    assert len(rows) == len(PAIRS) and {r["pair"] for r in rows} == set(PAIRS)
    assert all(r["trade_execution_allowed"] is False for r in rows)
    assert all(r["no_5m_signal_inputs"] for r in rows)
    print(json.dumps({"status": "PUBLISHED", "count": len(rows),
                      "macro_metric_count": len(metrics), "spread_count": len(spreads),
                      "macro_evidence_pairs": sum(bool(r["macro_directional_evidence"]) for r in rows),
                      "top_five": [{"pair": r["pair"], "direction": r["direction"],
                                    "alignment": r["macro_alignment"]} for r in rows[:5]]}))

if __name__ == "__main__":
    main()
