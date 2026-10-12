"""Combine timestamped TradingView indicators with ForexToolkits OHLC data.

Outputs conditional rotation candidates, never executable orders.
Uses closed candles for price-structure tests, avoids future leakage.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
TF = {"15m": "M15", "30m": "M30", "1H": "H1", "4H": "H4", "1D": "D1"}
MAX_TECH_AGE_MIN = 35
MAX_VOL_AGE_MIN = 35
MAX_CANDLE_AGE_MIN = {"M15": 18, "M30": 33, "H1": 75, "H4": 300, "D1": 4500}


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except (ValueError, TypeError):
        return None


def age_minutes(now, dt):
    return (now - dt).total_seconds() / 60 if dt else None


def valid_age(age, maximum):
    return age is not None and -5 <= age <= maximum


def pip_size(pair):
    return 0.01 if pair.endswith("JPY") else 0.0001


def number(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else None
    except (ValueError, TypeError):
        return None


def candle_metrics(pair, frame, now, tf, clock_offset_seconds=0):
    try:
        ts = frame["t"]
        o, h, l, c = (frame[k] for k in ("o", "h", "l", "c"))
        n = len(ts)
        if n < 25 or any(len(a) != n for a in (o, h, l, c)):
            return None, "insufficient_or_misaligned_candles"
        # Latest bar may still be forming: exclude it for confirmed structure.
        values = [list(map(float, a[:-1])) for a in (o, h, l, c)]
        oo, hh, ll, cc = values
        if not all(math.isfinite(x) for a in values for x in a):
            return None, "invalid_candle_value"
        if any(hh[i] < max(oo[i], cc[i], ll[i]) or ll[i] > min(oo[i], cc[i]) for i in range(len(cc))):
            return None, "invalid_ohlc"
        # Last closed candle timestamp is the OPEN time; its close is one TF later.
        seconds = {"M15": 900, "M30": 1800, "H1": 3600, "H4": 14400, "D1": 86400}[tf]
        close_dt = datetime.fromtimestamp(int(ts[-2]) + seconds - clock_offset_seconds, UTC)
        age = age_minutes(now, close_dt)
        if not valid_age(age, MAX_CANDLE_AGE_MIN[tf]):
            return None, "stale_candles"
        pip = pip_size(pair)
        tr = [max(hh[i]-ll[i], abs(hh[i]-cc[i-1]), abs(ll[i]-cc[i-1])) / pip for i in range(1,len(cc))]
        atr5 = sum(tr[-5:]) / 5
        atr14 = sum(tr[-14:]) / 14
        prior_high = max(hh[-7:-1])
        prior_low = min(ll[-7:-1])
        latest = cc[-1]
        earlier_high = max(hh[-13:-7])
        earlier_low = min(ll[-13:-7])
        structure = ("higher_highs_higher_lows" if prior_high > earlier_high and prior_low > earlier_low
                     else "lower_highs_lower_lows" if prior_high < earlier_high and prior_low < earlier_low
                     else "mixed")
        # Breakout requires latest closed candle to CLOSE beyond prior 6 closed bars.
        breakout_up = latest > prior_high
        breakout_down = latest < prior_low
        # Simple closed-candle momentum, not a prediction.
        momentum_pips = (latest - cc[-4]) / pip
        # Trace the most recent contiguous directional leg across up to 20 closed bars.
        # This is a proxy for move origin, not a confirmed market turning point.
        leg_sign = 1 if cc[-1] >= cc[-2] else -1
        start = len(cc) - 2
        for i in range(len(cc)-2, max(0,len(cc)-21), -1):
            if (cc[i+1]-cc[i])*leg_sign <= 0:
                break
            start = i
        leg_pips = (cc[-1]-cc[start])/pip
        displacement_20 = (cc[-1]-cc[-21])/pip
        excursion_up_20 = (max(hh[-20:])-cc[-21])/pip
        excursion_down_20 = (cc[-21]-min(ll[-20:]))/pip
        leg_start_dt = datetime.fromtimestamp(int(ts[start])+seconds-clock_offset_seconds, UTC)
        return {
            "leg_origin_proxy_utc":leg_start_dt.isoformat(),
            "leg_origin_proxy_price":cc[start],
            "leg_move_pips":round(leg_pips,2),
            "leg_bars":len(cc)-1-start,
            "displacement_20_pips":round(displacement_20,2),
            "excursion_up_20_pips":round(excursion_up_20,2),
            "excursion_down_20_pips":round(excursion_down_20,2),
            "last_closed_candle_utc": close_dt.isoformat(),
            "candle_age_minutes": round(age, 1),
            "closed_price": latest,
            "prior_6_high": prior_high,
            "prior_6_low": prior_low,
            "structure": structure,
            "breakout_up": breakout_up,
            "breakout_down": breakout_down,
            "momentum_3_bars_pips": round(momentum_pips, 2),
            "atr5_pips": round(atr5, 2),
            "atr14_pips": round(atr14, 2),
            "atr_expansion_ratio": round(atr5 / atr14, 3) if atr14 else None,
            "swing_high_20": max(hh[-20:]), "swing_low_20": min(ll[-20:]),
            "previous_closed_high": hh[-1], "previous_closed_low": ll[-1],
        }, None
    except (KeyError, TypeError, ValueError, OverflowError, OSError):
        return None, "malformed_candles"


def tech_metrics(frame):
    if frame.get("status") != "ok":
        return None
    ind = frame.get("indicators", {})
    price = number(ind.get("close"))
    e10, e20, e50, e100, e200 = [number(ind.get("EMA" + str(n))) for n in (10,20,50,100,200)]
    rsi = number(ind.get("RSI"))
    macd = number(ind.get("MACD.macd"))
    signal = number(ind.get("MACD.signal"))
    if price is None or e10 is None or e20 is None:
        return None
    return {
        "close": price, "ema10": e10, "ema20": e20,
        "ema50": e50, "ema100": e100, "ema200": e200,
        "rsi": rsi, "macd_hist": macd-signal if macd is not None and signal is not None else None,
        "recommendation": frame.get("summary", {}).get("RECOMMENDATION", "UNKNOWN"),
        "bullish": price > e10 > e20,
        "bearish": price < e10 < e20,
    }


def analyze(pair, tech, vol, now):
    output = {"pair": pair, "status": "WAIT", "direction": "NONE", "stage": "WAIT",
              "confidence": "UNVERIFIED", "entry": None, "stop": None, "tp1": None, "tp2": None,
              "reasons": [], "timeframes": {}}
    t_time = parse_time(tech.get("collected_at_utc"))
    v_time = parse_time(vol.get("collected_at_utc"))
    t_age, v_age = age_minutes(now,t_time), age_minutes(now,v_time)
    output["technical_age_minutes"] = round(t_age,1) if t_age is not None else None
    output["volatility_age_minutes"] = round(v_age,1) if v_age is not None else None
    if not valid_age(t_age,MAX_TECH_AGE_MIN) or not valid_age(v_age,MAX_VOL_AGE_MIN):
        output["status"] = "DATA_UNAVAILABLE"
        output["reasons"].append("STALE_INPUT_FEED")
        return output
    vpair = vol.get("pairs",{}).get(pair)
    if not vpair:
        output["status"] = "DATA_UNAVAILABLE"
        output["reasons"].append("NO_VOLATILITY_PAIR")
        return output
    # ForexToolkits may timestamp candles in its server-local clock.
    # Infer only a whole-hour offset from its own source timestamp and collection time.
    # Reject ambiguous offsets rather than assuming UTC or silently accepting future bars.
    clock_offset_seconds = 0
    source_ts = number(vol.get("source_timestamp"))
    if source_ts is not None and v_time is not None:
        offset = source_ts - v_time.timestamp()
        rounded = round(offset / 3600) * 3600
        if abs(offset - rounded) <= 600 and abs(rounded) <= 12 * 3600:
            clock_offset_seconds = rounded
        elif abs(offset) > 600:
            output["status"] = "DATA_UNAVAILABLE"
            output["reasons"].append("AMBIGUOUS_SOURCE_CLOCK")
            return output
    output["source_clock_offset_hours"] = clock_offset_seconds / 3600
    for t, vt in TF.items():
        tm = tech_metrics(tech.get("pairs",{}).get(pair,{}).get(t,{}))
        vm, error = candle_metrics(pair,vpair.get("tf",{}).get(vt,{}),now,vt,clock_offset_seconds)
        output["timeframes"][t] = {"technical":tm,"candles":vm,"error":error}
    if any(t not in output["timeframes"] for t in ("15m", "30m")):
        output["status"] = "DATA_UNAVAILABLE"
        output["reasons"].append("MISSING_TIMEFRAME_RESULTS")
        return output
    m15 = output["timeframes"]["15m"]
    m30 = output["timeframes"]["30m"]
    if any(not x["technical"] or not x["candles"] for x in (m15,m30)):
        output["status"] = "DATA_UNAVAILABLE"
        output["reasons"].append("MISSING_OR_STALE_EXECUTION_TIMEFRAME")
        return output
    a,b = [x["technical"] for x in (m15,m30)]
    x,y = [q["candles"] for q in (m15,m30)]
    # Direction is detected before entry quality. A single lagging RSI/EMA cannot
    # suppress a developing move; score independent price and indicator evidence.
    candidates = []
    for direction, sign in (("BUY", 1), ("SELL", -1)):
        momentum = x["momentum_3_bars_pips"] * sign
        breakout = x["breakout_up"] if sign == 1 else x["breakout_down"]
        structure = x["structure"] == ("higher_highs_higher_lows" if sign == 1 else "lower_highs_lower_lows")
        ema = a["bullish"] if sign == 1 else a["bearish"]
        close_vs_ema = (a["close"] - a["ema20"]) * sign > 0
        rsi = a["rsi"] is not None and (a["rsi"] >= 50 if sign == 1 else a["rsi"] <= 50)
        thirty_momentum = y["momentum_3_bars_pips"] * sign > 0
        thirty_rsi = b["rsi"] is not None and (b["rsi"] >= 50 if sign == 1 else b["rsi"] <= 50)
        # Momentum/price structure are primary; slower indicators are bonuses.
        score = (3 if breakout else 0) + (2 if momentum > 0 else 0) + (2 if structure else 0)
        score += int(ema) + int(close_vs_ema) + int(rsi) + int(thirty_momentum) + int(thirty_rsi)
        if score >= 4 and (momentum > 0 or breakout):
            candidates.append((score, direction, sign, breakout, momentum))
    output["rotation_scores"] = {direction: score for score, direction, *_ in candidates}
    if candidates:
        candidates.sort(reverse=True)
        score, direction, sign, breakout, momentum = candidates[0]
        output["direction"] = direction
        output["confidence"] = "TECHNICAL_ONLY"
        output["direction_score"] = score
        output["reasons"].append("15m_price_action_scored_without_mandatory_30m_confirmation")
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            output["status"] = "CONFLICTING_DIRECTION"
            output["direction"] = "NONE"
            output["reasons"].append("bull_bear_scores_tied")
        else:
            move_pips = max(abs(x["momentum_3_bars_pips"]), abs(x["leg_move_pips"]))
            atr = x["atr14_pips"]
            excursion = x["excursion_up_20_pips"] if sign == 1 else x["excursion_down_20_pips"]
            directional_displacement = x["displacement_20_pips"] * sign
            thirty_displacement = y["displacement_20_pips"] * sign
            output["move_maturity"] = {"15m_excursion_20_pips":round(excursion,1),
                "15m_net_displacement_20_pips":round(directional_displacement,1),
                "30m_net_displacement_20_pips":round(thirty_displacement,1),
                "latest_15m_leg_pips":round(move_pips,1)}
            # EARLY is reserved for genuinely new moves, not a fresh candle leg
            # within an existing 20-30 pip trend. Thresholds are conservative
            # heuristic filters, not a proof of profitable entry timing.
            mature = directional_displacement >= 15 or thirty_displacement >= 20
            stretched = (directional_displacement >= 30 or thirty_displacement >= 40
                         or excursion >= 35 or (atr > 0 and move_pips >= 2.0 * atr))
            output["stage"] = ("EXTENDED" if stretched else "CONTINUATION" if mature
                               else "CONFIRMING" if breakout else "EARLY")
            if mature: output["reasons"].append("EXISTING_MULTI_HOUR_DIRECTIONAL_MOVE_NOT_EARLY")
            output["status"] = "DO_NOT_CHASE" if output["stage"] == "EXTENDED" else "WATCH_FOR_ENTRY"
            output["move_origin_proxy"] = {
                "utc": x["leg_origin_proxy_utc"], "price": x["leg_origin_proxy_price"],
                "moved_pips": x["leg_move_pips"], "bars": x["leg_bars"],
                "method": "contiguous_closed_15m_directional_closes_proxy"
            }
            output["entry"] = {
                "type": "CONDITIONAL_BREAKOUT_OR_PULLBACK",
                "level": x["prior_6_high"] if sign == 1 else x["prior_6_low"],
                "condition": "Monitor break/retest or shallow pullback; independently verify quote, spread, nearby levels and news before execution"
            }
            output["reasons"].append("15m_direction_detected")
            if breakout:
                output["reasons"].append("15m_closed_breakout")
    else:
        # Detect emerging pressure inside a range before momentum confirmation.
        # Research watch only: never turn this into an executable entry.
        recent_high = max(x["prior_6_high"], x["previous_closed_high"])
        recent_low = min(x["prior_6_low"], x["previous_closed_low"])
        width_pips = (recent_high - recent_low) / pip_size(pair)
        compression = width_pips <= max(10.0, 2.0 * x["atr14_pips"])
        momentum = x["momentum_3_bars_pips"]
        close = x["closed_price"]
        location = (close - recent_low) / (recent_high - recent_low) if recent_high > recent_low else 0.5
        ema_delta = (a["close"] - a["ema20"]) / pip_size(pair)
        # Favor directional pressure near a boundary, not a blind RSI/EMA reversal.
        early_buy = compression and location >= 0.65 and momentum > 0 and ema_delta >= -2
        early_sell = compression and location <= 0.35 and momentum < 0 and ema_delta <= 2
        output["range_watch"] = {
            "range_high": round(recent_high, 5 if not pair.endswith("JPY") else 3),
            "range_low": round(recent_low, 5 if not pair.endswith("JPY") else 3),
            "range_width_pips": round(width_pips, 1),
            "compressed": compression,
            "location_in_range": round(location, 2),
            "momentum_3_bars_pips": momentum,
            "note": "6-bar 15m range proxy, not measured multi-hour consolidation duration"
        }
        if early_buy != early_sell:
            direction = "BUY" if early_buy else "SELL"
            output["direction"] = direction
            output["stage"] = "EARLY_WATCH"
            output["status"] = "WATCH_FOR_TRIGGER"
            output["confidence"] = "PRECONFIRMATION_TECHNICAL_ONLY"
            output["entry"] = {
                "type": "CONDITIONAL_RANGE_BREAK",
                "level": recent_high if early_buy else recent_low,
                "condition": "Wait for 15m break and retest or a verified shallow pullback; check news, spread, yields and cross-pair strength before trading"
            }
            output["reasons"].append("COMPRESSED_RANGE_WITH_DIRECTIONAL_PRESSURE_PRECONFIRMATION")
        else:
            output["reasons"].append("NO_DIRECTION_WITH_MINIMUM_PRICE_ACTION_EVIDENCE")
    # 15m + 30m agreement is the earliest directional trade candidate.
    # 1H adds confirmation, while 4H is context. Neither is a veto.
    # Trade candidate is NOT an order: live quote, spread, news and risk checks
    # must pass before an actual execution decision.
    def vote(row):
        t, c = row.get("technical"), row.get("candles")
        if not t or not c:
            return "UNAVAILABLE"
        buy = int(t["bullish"]) + int(t["rsi"] is not None and t["rsi"] >= 50) + int(c["momentum_3_bars_pips"] > 0)
        sell = int(t["bearish"]) + int(t["rsi"] is not None and t["rsi"] <= 50) + int(c["momentum_3_bars_pips"] < 0)
        if buy >= 2 and buy > sell:
            return "BUY"
        if sell >= 2 and sell > buy:
            return "SELL"
        return "MIXED"
    votes = {tf: vote(output["timeframes"][tf]) for tf in ("15m", "30m", "1H")}
    # 1H: EMA20 is directional; EMA50 adds strength, not a veto.
    hourly = output["timeframes"]["1H"]["technical"]
    if hourly and hourly.get("close") is not None and hourly.get("ema20") is not None:
        votes["1H"] = ("BUY" if hourly["close"] > hourly["ema20"] else
                       "SELL" if hourly["close"] < hourly["ema20"] else "MIXED")
    hourly_ema50 = hourly.get("ema50") if hourly else None
    output["hourly_ema_confirmation"] = {
        "direction": votes["1H"],
        "ema20_rule": "PRICE_VS_EMA20",
        "ema50_strength": (
            "STRONGER_BUY" if hourly and hourly_ema50 is not None and
            hourly["close"] > hourly["ema20"] and hourly["close"] > hourly_ema50 else
            "STRONGER_SELL" if hourly and hourly_ema50 is not None and
            hourly["close"] < hourly["ema20"] and hourly["close"] < hourly_ema50 else
            "EMA20_ONLY_OR_MIXED")
    }
    # 4H: trend location versus EMA20; EMA10 crossing is acceleration evidence.
    h4 = output["timeframes"]["4H"]
    h4tech = h4.get("technical")
    h4candles = h4.get("candles")
    h4state = {"ema20_position": "UNAVAILABLE", "ema10_break": "UNVERIFIED"}
    if h4tech and h4tech.get("close") is not None:
        h4price = h4tech["close"]
        h4ema20 = h4tech.get("ema20")
        h4ema10 = h4tech.get("ema10")
        if h4ema20 is not None:
            h4state["ema20_position"] = ("ABOVE_BULLISH" if h4price > h4ema20 else
                "BELOW_BEARISH" if h4price < h4ema20 else "AT_EMA20")
        if h4ema10 is not None and h4candles:
            # A cross requires two consecutive CLOSED 4H candle closes and
            # a corresponding historical EMA10. Only current EMA10 is available
            # in this snapshot, so never assert a historical EMA cross.
            h4state["ema10_position"] = ("ABOVE" if h4price > h4ema10 else
                "BELOW" if h4price < h4ema10 else "AT")
            h4state["ema10_break"] = "NOT_VERIFIED_NO_HISTORICAL_EMA10"
    output["four_hour_ema_context"] = h4state

    early_aligned = votes["15m"] in ("BUY", "SELL") and votes["15m"] == votes["30m"]
    confirmed = early_aligned and votes["1H"] == votes["15m"]
    output["timeframe_votes"] = votes
    output["early_15m_30m_aligned"] = early_aligned
    output["confirmed_15m_30m_1h"] = confirmed
    output["trade_qualification"] = ("CONFIRMED_3TF_TECHNICAL" if confirmed
        else "EARLY_2TF_TECHNICAL" if early_aligned else "NOT_ALIGNED")
    if early_aligned:
        output["direction"] = votes["15m"]
        output["confidence"] = "TECHNICAL_ALIGNMENT_ONLY"
        output["reasons"].append("15M_30M_ALIGNED_EARLY_TRADE_CANDIDATE")
        if not confirmed:
            output["reasons"].append("1H_NOT_YET_CONFIRMED")
        if output["stage"] in ("WAIT", "EARLY_WATCH"):
            output["stage"] = "CONFIRMING" if confirmed else "EARLY"
            output["status"] = "WATCH_FOR_ENTRY"
            level = x["prior_6_high"] if votes["15m"] == "BUY" else x["prior_6_low"]
            output["entry"] = {"type": "CONDITIONAL_BREAK_OR_RETEST", "level": level,
                "condition": "Confirm fresh price, spread, news, risk/reward and entry trigger before execution"}
    elif output["direction"] in ("BUY", "SELL"):
        output["reasons"].append("15M_30M_NOT_ALIGNED_DIRECTIONAL_WATCH_ONLY")
    # Higher-timeframe classification is separate from intraday qualification.
    # Do not promote a countertrend bounce into a confirmed reversal.
    h4 = output["timeframes"].get("4H", {})
    daily = output["timeframes"].get("1D", {})
    hour = output["timeframes"].get("1H", {})
    def bias(row):
        t, c = row.get("technical"), row.get("candles")
        if not t or not c:
            return "UNAVAILABLE"
        up = t["close"] > t["ema20"] and t["ema20"] > t["ema50"] if t["ema50"] is not None else False
        down = t["close"] < t["ema20"] and t["ema20"] < t["ema50"] if t["ema50"] is not None else False
        structure = c["structure"]
        if up and structure == "higher_highs_higher_lows": return "BULLISH"
        if down and structure == "lower_highs_lower_lows": return "BEARISH"
        return "MIXED"
    output["higher_timeframe"] = {
        "daily_bias": bias(daily), "h4_bias": bias(h4), "h1_bias": bias(hour),
        "source": "closed_candle_structure_and_EMA20_EMA50",
        "daily_levels": (daily.get("candles") or {}),
        "h4_levels": (h4.get("candles") or {}),
    }
    dominant = output["higher_timeframe"]["h4_bias"]
    direction = output["direction"]
    if dominant == "UNAVAILABLE" or output["higher_timeframe"]["daily_bias"] == "UNAVAILABLE":
        output["trade_type"] = "HIGHER_TIMEFRAME_UNVERIFIED"
        output["entry"] = None
        output["reasons"].append("HIGHER_TIMEFRAME_UNVERIFIED_DIRECTION_ONLY")
    elif direction not in ("BUY", "SELL"):
        output["trade_type"] = "NO_ROTATION"
    elif dominant == "MIXED":
        output["trade_type"] = "RANGE_OR_TRANSITION"
    elif (dominant == "BULLISH" and direction == "BUY") or (dominant == "BEARISH" and direction == "SELL"):
        output["trade_type"] = "TREND_CONTINUATION"
    else:
        output["trade_type"] = "COUNTERTREND_PULLBACK"
        output["reasons"].append("COUNTERTREND_NOT_CONFIRMED_REVERSAL")
    # Distance to the nearest 4H and Daily swing boundary in the signal direction.
    pip = pip_size(pair)
    price = (output["timeframes"].get("15m", {}).get("candles") or {}).get("closed_price")
    obstacles = []
    if price is not None and direction in ("BUY", "SELL"):
        for name, row in (("4H", h4), ("1D", daily)):
            candle = row.get("candles") or {}
            key = "swing_high_20" if direction == "BUY" else "swing_low_20"
            level = candle.get(key)
            if level is not None:
                distance = (level-price)/pip if direction == "BUY" else (price-level)/pip
                if distance > 0:
                    obstacles.append({"timeframe": name, "level": level, "distance_pips": round(distance,1)})
    output["higher_timeframe"]["nearest_obstacle"] = min(obstacles, key=lambda x:x["distance_pips"]) if obstacles else None
    output["higher_timeframe"]["available_room_verified"] = bool(obstacles)
    if output.get("trade_type") == "COUNTERTREND_PULLBACK":
        nearest = output["higher_timeframe"]["nearest_obstacle"]
        if nearest and nearest["distance_pips"] < 20:
            output["reasons"].append("COUNTERTREND_LESS_THAN_20_PIPS_TO_HTF_OBSTACLE")
            # Obstacle distance is advisory; 18 pips is not an automatic veto.
    if output["direction"] == "NONE":
        output["reasons"].append("NO_ALIGNED_15m_30m_ROTATION")
        if output["status"] != "CONFLICTING_DIRECTION":
            output["status"] = "NO_TRADE"
    # Divergence invalidates executable readiness but retains observed directional research.\n    # Warn on discrepancies across providers (not assumed identical pricing).
    diff = abs(a["close"] - x["closed_price"]) / pip_size(pair)
    output["price_source_difference_pips"] = round(diff,1)
    if diff > max(5, x["atr14_pips"]):
        output["status"] = "DATA_UNAVAILABLE"
        output["entry"] = None
        output["reasons"].append("PRICE_FEED_DIVERGENCE")
    output["reasons"].append("REQUIRES_NEWS_YIELDS_CROSS_PAIR_AND_EXECUTABLE_PRICE_CHECK")
    return output


def main():
    now = datetime.now(UTC)
    tech = json.loads(Path("fx_technicals.json").read_text(encoding="utf-8"))
    vol = json.loads(Path("fx_volatility.json").read_text(encoding="utf-8"))
    results = [analyze(pair,tech,vol,now) for pair in sorted(tech.get("pairs",{}))]
    payload = {"generated_at_utc":now.isoformat(), "technical_source_utc":tech.get("collected_at_utc"),
               "volatility_source_utc":vol.get("collected_at_utc"),
               "source_volatility_freshness":"unverified_upstream",
               "scope":"technical_rotation_candidates_only_not_live_trade_signals",
               "method":"closed_candles; EMA10/20 from TradingView; ATR5/14 from ForexToolkits",
               "pairs":results}
    Path("fx_rotation_signals.json").write_text(json.dumps(payload,indent=2),encoding="utf-8")
    print("Rotation candidates:",len(results))
    for r in results:
        print(r["pair"],r["direction"],r["stage"],r["status"])


if __name__ == "__main__":
    main()
