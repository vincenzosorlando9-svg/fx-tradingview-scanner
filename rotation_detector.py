"""Combine timestamped TradingView indicators with ForexToolkits OHLC data.

Outputs conditional rotation candidates, never executable orders.
Uses closed candles for price-structure tests, avoids future leakage.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

UTC = timezone.utc
TF = {"5m": "M5", "15m": "M15", "30m": "M30", "1H": "H1"}
MAX_TECH_AGE_MIN = 35
MAX_VOL_AGE_MIN = 35
MAX_CANDLE_AGE_MIN = {"M5": 20, "M15": 40, "M30": 65, "H1": 125}


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
        seconds = {"M5": 300, "M15": 900, "M30": 1800, "H1": 3600}[tf]
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
        return {
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
        output["reasons"].append("STALE_INPUT_FEED")
        return output
    vpair = vol.get("pairs",{}).get(pair)
    if not vpair:
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
            output["reasons"].append("AMBIGUOUS_SOURCE_CLOCK")
            return output
    output["source_clock_offset_hours"] = clock_offset_seconds / 3600
    for t, vt in TF.items():
        tm = tech_metrics(tech.get("pairs",{}).get(pair,{}).get(t,{}))
        vm, error = candle_metrics(pair,vpair.get("tf",{}).get(vt,{}),now,vt,clock_offset_seconds)
        output["timeframes"][t] = {"technical":tm,"candles":vm,"error":error}
    if any(t not in output["timeframes"] for t in ("5m", "15m", "30m")):
        output["reasons"].append("MISSING_TIMEFRAME_RESULTS")
        return output
    m5 = output["timeframes"]["5m"]
    m15 = output["timeframes"]["15m"]
    m30 = output["timeframes"]["30m"]
    if any(not x["technical"] or not x["candles"] for x in (m5,m15,m30)):
        output["reasons"].append("MISSING_OR_STALE_EXECUTION_TIMEFRAME")
        return output
    a,b,c = [x["technical"] for x in (m5,m15,m30)]
    x,y,z = [q["candles"] for q in (m5,m15,m30)]
    # A directional candidate requires multi-timeframe agreement and price/candle alignment.
    for direction, sign in (("BUY",1),("SELL",-1)):
        aligned = (a["bullish"] and b["bullish"]) if sign == 1 else (a["bearish"] and b["bearish"])
        higher = (c["rsi"] is not None and c["rsi"] >= 48) if sign == 1 else (c["rsi"] is not None and c["rsi"] <= 52)
        momentum = x["momentum_3_bars_pips"] * sign > 0
        breakout = x["breakout_up"] if sign == 1 else x["breakout_down"]
        if aligned and higher and momentum:
            output["direction"] = direction
            expansion = x["atr_expansion_ratio"] is not None and x["atr_expansion_ratio"] >= 1.15
            output["stage"] = "CONFIRMING" if breakout and expansion else "EARLY" if not breakout else "CONFIRMING"
            output["status"] = "WATCH_FOR_ENTRY"
            output["confidence"] = "TECHNICAL_ONLY"
            output["reasons"] += ["5m_15m_ema10_20_aligned", "30m_rsi_not_opposing", "closed_5m_momentum_aligned"]
            if breakout:
                output["reasons"].append("5m_closed_candle_breakout")
            if expansion:
                output["reasons"].append("5m_atr_expansion")
            if x["atr14_pips"] > 0 and abs(x["momentum_3_bars_pips"]) > 2.5 * x["atr14_pips"]:
                output["stage"] = "EXTENDED"
                output["status"] = "DO_NOT_CHASE"
                output["reasons"].append("3_bar_move_exceeds_2_5x_atr")
            # Conditional breakout boundary only. No stops/TP without verified
            # executable prices, spread and market/catalyst confirmation.
            output["entry"] = {"type":"CONDITIONAL_BREAKOUT_RETEST",
                               "level":x["prior_6_high"] if sign==1 else x["prior_6_low"],
                               "condition":"New closed 5m candle beyond level, then hold/retest; confirm current quote and spread"}
            break
    if output["direction"] == "NONE":
        output["reasons"].append("NO_ALIGNED_5m_15m_ROTATION")
    # Warn on discrepancies across providers (not assumed identical pricing).
    diff = abs(a["close"] - x["closed_price"]) / pip_size(pair)
    output["price_source_difference_pips"] = round(diff,1)
    if diff > max(5, x["atr14_pips"]):
        output["status"] = "WAIT"
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
