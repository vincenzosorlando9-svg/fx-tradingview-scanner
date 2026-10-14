"""Fail-closed quote validation for the 11-pair FX universe.

This module validates normalized observations from future licensed data adapters.
It does not retrieve prices or create trading signals.
"""
from datetime import datetime, timezone

PAIRS=("AUDUSD","NZDUSD","USDCAD","NZDJPY","AUDJPY","USDJPY","EURGBP","EURJPY","EURCAD","GBPUSD","EURUSD")
JPY_PAIRS=frozenset(p for p in PAIRS if p.endswith("JPY"))

def pip_size(pair):
    if pair not in PAIRS:
        raise ValueError("Unsupported currency pair")
    return 0.01 if pair in JPY_PAIRS else 0.0001

def validate_quote(quote,now=None,max_age_seconds=180):
    """Return (accepted, reason). Reject stale, inverted, missing and future quotes."""
    if not isinstance(quote,dict):
        return False,"invalid_payload"
    pair=quote.get("pair")
    if pair not in PAIRS:
        return False,"unsupported_pair"
    try:
        bid=float(quote["bid"])
        ask=float(quote["ask"])
        observed=datetime.fromisoformat(quote["observed_at"].replace("Z","+00:00"))
    except (KeyError,TypeError,ValueError,AttributeError):
        return False,"invalid_quote_fields"
    if observed.tzinfo is None:
        return False,"missing_timezone"
    import math
    if not math.isfinite(bid) or not math.isfinite(ask) or bid<=0 or ask<=bid:
        return False,"invalid_bid_ask"
    if not isinstance(quote.get("source"),str) or not quote["source"].strip():
        return False,"missing_source"
    now=now or datetime.now(timezone.utc)
    age=(now-observed).total_seconds()
    if age< -15:
        return False,"future_timestamp"
    if age>max_age_seconds:
        return False,"stale_quote"
    return True,"verified_structure_only"

def reconcile_quotes(quotes,now=None):
    """Validate source structure, then compare independent quote midpoints.
    Structural validity is not proof of a genuine market observation.
    """
    valid=[]
    rejected=[]
    for quote in quotes:
        ok,reason=validate_quote(quote,now=now)
        (valid if ok else rejected).append(quote if ok else {"quote":quote,"reason":reason})
    grouped={}
    for quote in valid:
        grouped.setdefault(quote["pair"],[]).append(quote)
    outcomes={}
    for pair in PAIRS:
        observations=grouped.get(pair,[])
        distinct_sources={q["source"] for q in observations}
        if len(distinct_sources)<2:
            outcomes[pair]={"status":"UNAVAILABLE","reason":"requires_two_independent_sources"}
            continue
        mids=[(float(q["bid"])+float(q["ask"]))/2 for q in observations]
        if (max(mids)-min(mids))/pip_size(pair)>3:
            outcomes[pair]={"status":"CONFLICT","reason":"midpoint_disagreement_over_3_pips"}
            continue
        outcomes[pair]={"status":"STRUCTURALLY_CONSISTENT","source_count":len(distinct_sources),
                        "reason":"not_yet_authenticated_or_verified_against_publisher"}
    return {"pairs":outcomes,"rejected":rejected,"trading_evidence_gate_pass":False}
