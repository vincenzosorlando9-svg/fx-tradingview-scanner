#!/usr/bin/env python3
"""Enforce exact 15m/30m/1H CLOSED candle targets for a four-scan UTC schedule.

Run targets :02 :17 :32 :47 UTC. A data fetch timestamp alone never
establishes candle freshness. No trading order or directional interpretation.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fx_early_rotation import PAIRS, closed_bars, server_offset, parse

UTC=timezone.utc
SLOTS=(2,17,32,47)
TF_SECONDS={"M15":900,"M30":1800,"H1":3600}
CONTINUITY={"M15":4,"M30":3,"H1":3}
MAX_START_DELAY_SECONDS=240
NY=ZoneInfo("America/New_York")


def expected_slot(now):
    if now.tzinfo is None:
        raise ValueError("NAIVE_CLOCK_IS_NOT_ALLOWED")
    now=now.astimezone(UTC)
    base=(now.minute//15)*15
    due=now.replace(minute=base+2,second=0,microsecond=0)
    if now<due:
        due-=timedelta(minutes=15)
    close=due-timedelta(minutes=2)
    return {"scheduled_for_utc":due.isoformat(),
            "candle_slot_close_utc":close.isoformat(),
            "seconds_after_target":round((now-due).total_seconds(),3),
            "accepting_new_scan":0<=(now-due).total_seconds()<=MAX_START_DELAY_SECONDS}


def market_open(when):
    dt=when.astimezone(NY)
    dow=dt.weekday()
    hm=dt.hour*60+dt.minute
    # Spot FX weekend; DST aware. No fictitious weekend candle continuity.
    return not ((dow==4 and hm>=17*60) or dow==5 or
                (dow==6 and hm<17*60))


def continuous_during_market_hours(previous_close,next_close,period):
    """Missing trading-hours candle blocks; normal spot-FX weekend gap doesn't."""
    if next_close<=previous_close:
        return False
    if (next_close-previous_close).total_seconds()==period:
        return True
    cursor=previous_close+timedelta(seconds=period)
    while cursor<next_close:
        # A candle belongs to the session of its OPEN, not its CLOSE.
        if market_open(cursor-timedelta(seconds=period)):
            return False
        cursor+=timedelta(seconds=period)
    return True


def validate(vol,now,slot_close=None):
    """A snapshot PASS requires exact expected latest CLOSED bar on all 11 pairs.

    M30 and H1 are carried forward ONLY until their next actual close.
    Consecutive observed bar timestamps must be gapless during open market.
    """
    now=now.astimezone(UTC)
    requested=parse(slot_close) if slot_close else parse(expected_slot(now)["candle_slot_close_utc"])
    result={"status":"INVALID","evaluated_at_utc":now.isoformat(),
            "expected_scan_slot_close_utc":requested.isoformat() if requested else None,
            "source_collected_at_utc":vol.get("collected_at_utc"),
            "source_timestamp":vol.get("source_timestamp"),
            "validated_pairs":0,"required_pairs":len(PAIRS),
            "missing":[],"expected_closes":{},"observed_closes":{},
            "source_clock_correction_seconds":None,"signal_publication_allowed":False}
    if not requested:
        result["missing"].append("INVALID_EXPECTED_SLOT")
        return result
    offset=server_offset(vol)
    if offset is None:
        result["missing"].append("UNVERIFIABLE_SOURCE_SERVER_CLOCK")
        return result
    result["source_clock_correction_seconds"]=offset
    collected=parse(vol.get("collected_at_utc"))
    if not collected or not -timedelta(seconds=10)<=now-collected<=timedelta(minutes=3):
        result["missing"].append("SOURCE_FETCH_TIMESTAMP_STALE_OR_IN_FUTURE")
        return result
    for tf,period in TF_SECONDS.items():
        unix=int(requested.timestamp())
        expected=datetime.fromtimestamp((unix//period)*period,UTC)
        result["expected_closes"][tf]=expected.isoformat()
    for pair in PAIRS:
        frames=((vol.get("pairs") or {}).get(pair) or {}).get("tf") or {}
        complete=True
        observations={}
        for tf,period in TF_SECONDS.items():
            candles=closed_bars(frames.get(tf),tf,now,offset)
            expected=parse(result["expected_closes"][tf])
            observed=candles[-1]["close_dt"] if candles else None
            observations[tf]=observed.isoformat() if observed else None
            if observed!=expected:
                result["missing"].append(f"{pair}:{tf}:EXPECTED_{expected.isoformat()}_GOT_{observed.isoformat() if observed else 'NONE'}")
                complete=False
                continue
            last=candles[-CONTINUITY[tf]:]
            if len(last)<CONTINUITY[tf]:
                result["missing"].append(f"{pair}:{tf}:INSUFFICIENT_HISTORY")
                complete=False
            for prior,nxt in zip(last,last[1:]):
                if not continuous_during_market_hours(prior["close_dt"],nxt["close_dt"],period):
                    result["missing"].append(f"{pair}:{tf}:NON_CONTIGUOUS_HISTORY_{prior['close_utc']}")
                    complete=False
        result["observed_closes"][pair]=observations
        if complete:
            result["validated_pairs"]+=1
    if result["validated_pairs"]==len(PAIRS) and not result["missing"]:
        result["status"]="PASS_EXACT_CLOSED_M15_M30_H1"
        result["signal_publication_allowed"]=True
    else:
        result["status"]="WAIT_FOR_REQUIRED_CANDLES"
    return result
