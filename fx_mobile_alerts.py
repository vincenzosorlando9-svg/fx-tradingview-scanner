"""No-key iPhone research alerts via GitHub Issues assigned to repo owner.

Reads the *published in-job* 15m/30m early engine; 1H/4H are context only.
Only meaningful new directions, opposite-direction watches, confirmed flips,
JPY/USD clusters and early acceleration generate issues. Never trading orders.

GitHub Actions automatically supplies GITHUB_TOKEN (not a purchased API key).
No third-party webhooks, personal tokens, or 5m market data are used.
"""
import copy
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

UTC = timezone.utc
ET = ZoneInfo("America/New_York")
PAIRS = ("AUDUSD", "NZDUSD", "EURUSD", "GBPUSD", "USDJPY", "AUDJPY",
         "NZDJPY", "EURJPY", "EURCAD", "USDCAD", "EURGBP")
USD_PAIRS = ("AUDUSD", "NZDUSD", "EURUSD", "GBPUSD", "USDJPY", "USDCAD")
JPY_PAIRS = ("USDJPY", "AUDJPY", "NZDJPY", "EURJPY")
EUR_PAIRS = ("EURUSD", "EURJPY", "EURCAD", "EURGBP")
STATE_PATH = Path("fx_mobile_alert_state.json")
DASH_PATH = Path("fx_scan_dashboard.json")
EARLY_PATH = Path("fx_early_rotation.json")
MIN_SIGNAL_SCORE = 0.62
STRONG_OPPOSITE_SCORE = 3
ACCELERATION_PIPS = 8.0


def parse(value):
    if not isinstance(value, str):
        return None
    try:
        d = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return d.astimezone(UTC) if d.tzinfo else None
    except (ValueError, OverflowError):
        return None


def iso(now):
    return now.astimezone(UTC).isoformat()


def format_et(timestamp):
    d = parse(timestamp)
    return d.astimezone(ET).strftime("%b %d, %I:%M %p %Z") if d else "UNAVAILABLE"


def quiet_hours(now):
    t = now.astimezone(ET)
    return (t.weekday() == 4 and t.hour >= 14 or
            t.weekday() == 5 or
            t.weekday() == 6 and t.hour < 18)


def pip_size(pair):
    return 0.01 if pair.endswith("JPY") else 0.0001


def seed_state():
    return {"version": 1, "initialized_at_utc": None, "pairs": {},
            "clusters": {}, "recent_issue_keys": [], "last_issue": None}


def is_fresh(now, timestamp, max_minutes):
    ts = parse(timestamp)
    return ts is not None and -1 <= (now - ts).total_seconds() / 60 <= max_minutes


def eligible_pair(early_row, dash_row, now):
    if not early_row or not dash_row:
        return None
    if dash_row.get("source_valid") is not True:
        return None
    if (early_row.get("signal_timeframes") != ["15m", "30m"] or
            "5m" not in early_row.get("excluded_timeframes", [])):
        return None
    if early_row.get("execution_allowed") is not False:
        return None
    if (not is_fresh(now, early_row.get("latest_closed_m15_utc"), 21) or
            not is_fresh(now, early_row.get("latest_closed_m30_utc"), 41)):
        return None
    direction = early_row.get("direction")
    score = early_row.get("research_rank_score", 0) or 0
    if (direction not in ("BUY", "SELL") or not early_row.get("watch_only") or
            score < MIN_SIGNAL_SCORE):
        direction = "NONE"
    return {
        "pair": early_row["pair"], "direction": direction,
        "price": early_row.get("latest_closed_m15"),
        "closed15": early_row.get("latest_closed_m15_utc"),
        "closed30": early_row.get("latest_closed_m30_utc"),
        "stage": early_row.get("stage"),
        "score": score,
        "pressure": early_row.get("pressure_evidence") or {},
        "counter_watch": early_row.get("possible_opposite_rotation") or {},
        "invalidation": early_row.get("direction_invalidation_reference"),
        "event_risk": bool(early_row.get("event_within_120_min")),
        "fresh_trigger": bool(early_row.get("fresh_trigger")),
    }


def invalidated(bias, ref, price):
    if bias not in ("BUY", "SELL") or ref is None or price is None:
        return False
    return price <= ref if bias == "BUY" else price >= ref


def evidence_event(kind, snap, previous="NONE", reason=""):
    return {
        "type": kind, "pair": snap["pair"], "direction": snap["direction"],
        "previous": previous, "reason": reason,
        "price_15m_reference": snap["price"],
        "last_closed_15m_utc": snap["closed15"],
        "last_closed_30m_utc": snap["closed30"],
        "stage": snap["stage"], "research_score": round(snap["score"], 3),
        "pressure_evidence": snap["pressure"].get("evidence", []),
        "invalidation_reference": snap["invalidation"],
        "event_within_120_min": snap["event_risk"],
        "source": "CLOSED_15M_30M_RESEARCH_ONLY",
    }


def cluster_status(candidates):
    available = {p: x for p, x in candidates.items() if x}
    def strength(pair, currency):
        direction = available.get(pair, {}).get("direction")
        if direction not in ("BUY", "SELL"):
            return 0
        strong_when_buy = pair[:3] == currency
        return 1 if (direction == "BUY") == strong_when_buy else -1
    result = {}
    for currency, names, min_count in (
        ("USD", USD_PAIRS, 4),
        ("JPY", JPY_PAIRS, 3),
        ("EUR", EUR_PAIRS, 3),
    ):
        if sum(p in available for p in names) != len(names):
            continue
        for side in ("STRENGTH", "WEAKNESS"):
            supports = [p for p in names if strength(p, currency) ==
                        (1 if side == "STRENGTH" else -1)]
            if len(supports) >= min_count:
                result[currency + "_" + side] = supports
    return result


def evaluate(early, dashboard, previous, now):
    """Pure state transition. No API, no 5m reads. Returns events, new state."""
    state = copy.deepcopy(previous or seed_state())
    state.setdefault("pairs", {})
    state.setdefault("clusters", {})
    events = []
    e_at = early.get("generated_at_utc")
    if (quiet_hours(now) or early.get("quiet_hours") or
            early.get("feed_valid") is not True or
            early.get("status") != "RESEARCH_ONLY_PARTIAL_MACRO" or
            dashboard.get("source_versions_match") is not True or
            dashboard.get("early_rotation_generated_at_utc") != e_at or
            not is_fresh(now, e_at, 15)):
        return [], state
    epairs = {x.get("pair"): x for x in early.get("pairs", [])}
    dpairs = {x.get("pair"): x for x in dashboard.get("pairs", [])}
    if set(PAIRS) - set(epairs) or set(PAIRS) - set(dpairs):
        return [], state
    current = {p: eligible_pair(epairs[p], dpairs[p], now) for p in PAIRS}
    cluster_now = cluster_status(current)

    # First run builds a baseline without spamming eleven old signals.
    if not state.get("initialized_at_utc"):
        state["initialized_at_utc"] = iso(now)
        for pair, snap in current.items():
            state["pairs"][pair] = {
                "bias": snap["direction"] if snap else "NONE",
                "first_price": snap["price"] if snap else None,
                "invalidation": snap["invalidation"] if snap else None,
                "first_seen_utc": iso(now), "last_seen_utc": iso(now),
                "pending": None, "acceleration_sent": True,
                "last_alerted_bar": None, "baseline_only": True,
                "counter_pending": None,
            }
        state["clusters"] = {k: {"pairs": v, "first_seen_utc": iso(now)}
                              for k, v in cluster_now.items()}
        return [], state

    for pair, snap in current.items():
        if snap is None:
            # Do not turn missing data into a false reversal or a push alert.
            continue
        active = state["pairs"].setdefault(pair, {
            "bias": "NONE", "first_price": None, "invalidation": None,
            "first_seen_utc": None, "last_seen_utc": None, "pending": None,
            "acceleration_sent": False, "last_alerted_bar": None,
            "baseline_only": False,
            "counter_pending": None,
        })
        active.setdefault("counter_pending", None)
        prior = active.get("bias", "NONE")
        candidate = snap["direction"]
        price = snap["price"]
        bar = snap["closed15"]
        original_invalid = invalidated(prior, active.get("invalidation"), price)
        active["last_seen_utc"] = iso(now)

        # Preview a two-candle M15 + confirming M30 counter-rotation without
        # flipping the held trade direction. Do this BEFORE weak ranking/WAIT
        # vetoes: at 11 PM NZDJPY was still SELL (rank ~0.52) but rising.
        counter = snap.get("counter_watch") or {}
        counter_dir = counter.get("direction")
        early_warning_sent = False
        if (prior in ("BUY","SELL") and counter_dir in ("BUY","SELL")
                and counter_dir != prior and not original_invalid
                and (active.get("counter_pending") or {}).get("direction") != counter_dir):
            watch_snap = dict(snap, direction=counter_dir,
                              pressure={"evidence": counter.get("evidence",[])})
            reason=("PRE_FLIP_CLOSED_M15_M30_OPPOSITE_ROTATION; original "+prior+
                    " HELD. Two M15 closes, higher lows/lower highs and"
                    " supporting closed M30 change; no breakout required.")
            evt = evidence_event("OPPOSITE_WATCH", watch_snap, prior, reason)
            evt["early_counter_rotation"] = counter
            events.append(evt)
            active["counter_pending"] = {"direction":counter_dir,
                                         "first_closed_m15_utc":bar,
                                         "first_observed_at_utc":iso(now)}
            early_warning_sent = True

        if candidate == prior:
            active["pending"] = None
            if (prior in ("BUY", "SELL") and not active.get("acceleration_sent")
                    and price is not None and active.get("first_price") is not None):
                pips = (price - active["first_price"]) / pip_size(pair)
                pips = pips if prior == "BUY" else -pips
                if ACCELERATION_PIPS <= pips <= 30:
                    events.append(evidence_event("ACCELERATING", snap, prior,
                                                  f"{pips:.1f} pips since research alert"))
                    active["acceleration_sent"] = True
            continue

        if candidate == "NONE":
            if original_invalid and prior in ("BUY", "SELL"):
                if not active.get("baseline_only", False):
                    events.append(evidence_event("INVALIDATED", snap, prior,
                                                  "Closed 15m price invalidated original structure"))
                active.update(bias="NONE", pending=None, counter_pending=None, first_price=None,
                              invalidation=None, acceleration_sent=True,
                              baseline_only=False)
            else:
                active["pending"] = None
            continue

        if prior == "NONE":
            # Don't turn a tracking-only row without a new pressure observation into
            # a brand-new signal.
            if not snap["fresh_trigger"]:
                continue
            active.update(bias=candidate, counter_pending=None, first_seen_utc=iso(now),
                          first_price=price, invalidation=snap["invalidation"],
                          pending=None, acceleration_sent=False, baseline_only=False)
            events.append(evidence_event("NEW_DIRECTION", snap, prior,
                                          "First newly observed 15m/30m directional rotation"))
            continue

        # Opposite momentum against the current bias: issue a *watch* while
        # keeping the original direction, unless original structure breaks.
        pressure = snap["pressure"]
        strongly_opposite = (pressure.get("direction") == candidate and
                             (pressure.get("score") or 0) >= STRONG_OPPOSITE_SCORE)
        if not strongly_opposite:
            active["pending"] = None
            continue
        if original_invalid:
            active.update(bias=candidate, counter_pending=None, first_seen_utc=iso(now),
                          first_price=price, invalidation=snap["invalidation"],
                          pending=None, acceleration_sent=False, baseline_only=False)
            events.append(evidence_event("DIRECTION_CHANGED", snap, prior,
                                          "Original structure invalidated; opposite 15m/30m pressure"))
            continue

        pending = active.get("pending") or {}
        if pending.get("direction") != candidate:
            active["pending"] = {"direction": candidate,
                                 "first_bar_utc": bar, "last_bar_utc": bar,
                                 "distinct_closed_15m_bars": 1}
            if (not early_warning_sent and
                    (active.get("counter_pending") or {}).get("direction") != candidate):
                events.append(evidence_event("OPPOSITE_WATCH", snap, prior,
                                              "Original bias HELD; emerging contrary price pressure"))
        else:
            if bar != pending.get("last_bar_utc"):
                pending["distinct_closed_15m_bars"] = pending.get("distinct_closed_15m_bars", 1) + 1
                pending["last_bar_utc"] = bar
            active["pending"] = pending
            if pending["distinct_closed_15m_bars"] >= 2:
                active.update(bias=candidate, counter_pending=None, first_seen_utc=iso(now),
                              first_price=price, invalidation=snap["invalidation"],
                              pending=None, acceleration_sent=False, baseline_only=False)
                events.append(evidence_event("DIRECTION_CHANGED", snap, prior,
                                              "Opposite structure persisted across two distinct closed 15m bars"))

    for label, pairs in cluster_now.items():
        if label not in state["clusters"]:
            events.append({"type": "CURRENCY_CLUSTER", "label": label,
                           "pairs": pairs, "reason": "Multi-pair synchronized 15m/30m directions"})
    state["clusters"] = {k: {"pairs": v, "first_seen_utc": iso(now)}
                         for k, v in cluster_now.items()}
    return events, state


def alert_key(events):
    raw = json.dumps([{k: v for k, v in x.items() if k in
                       ("type", "pair", "direction", "previous",
                        "last_closed_15m_utc", "label")} for x in events],
                     sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def render_issue(events, early, now):
    clusters = [e for e in events if e["type"] == "CURRENCY_CLUSTER"]
    trends = [e for e in events if e["type"] != "CURRENCY_CLUSTER"]
    if clusters:
        x = clusters[0]
        title = "[FX CLUSTER] " + x["label"].replace("_", " ") + " (" + str(len(x["pairs"])) + " pairs)"
    elif trends:
        x = trends[0]
        d = x.get("direction", "")
        if x["type"] == "OPPOSITE_WATCH":
            title = "[FX EARLY WATCH] " + x["pair"] + " " + x["previous"] + " weakening / possible " + d
        elif x["type"] == "ACCELERATING":
            title = "[FX MOMENTUM] " + x["pair"] + " " + d
        elif x["type"] == "INVALIDATED":
            title = "[FX INVALIDATED] " + x["pair"] + " " + x["previous"]
        else:
            title = "[FX EARLY] " + x["pair"] + " " + d + (" +" + str(len(trends)-1) if len(trends)>1 else "")
    else:
        raise ValueError("No events")
    title = title[:120]
    key = alert_key(events)
    lines = [
        "## Early FX research alert — not a trade order",
        "",
        "**Scan:** " + format_et(early.get("generated_at_utc")),
        "**Alert evaluation:** " + now.astimezone(ET).strftime("%b %d, %I:%M %p %Z"),
        "**Method:** closed **15-minute and 30-minute** charts only for detection; 1H/4H context.",
        "**Execution:** NOT VERIFIED. Broker bid/ask, spread, news, liquidity and risk still require review.",
        "",
    ]
    for e in events:
        if e["type"] == "CURRENCY_CLUSTER":
            lines += [
                "### " + e["label"].replace("_", " "),
                "**Supporting pairs:** " + ", ".join(e["pairs"]),
                "Observed synchronized 15m/30m directions. Correlation is not independent confirmation.",
                "",
            ]
            continue
        prior = e.get("previous")
        lines += [
            "### " + e["type"].replace("_", " ") + " — " + e["pair"] + " " + e["direction"],
            "**Previous direction:** " + str(prior),
            "**15m reference close:** " + str(e.get("price_15m_reference")) +
                " (closed " + format_et(e.get("last_closed_15m_utc")) + ")",
            "**30m last close:** " + format_et(e.get("last_closed_30m_utc")),
            "**Research score:** " + str(e.get("research_score")) + " (not probability)",
            "**Status:** PRE-FLIP WATCH; original direction held" if e["type"]=="OPPOSITE_WATCH" else "**Status:** Technical watch only",
            "**Technical evidence:** " + (", ".join(e.get("pressure_evidence") or []) or "Directional momentum only"),
            "**Observed invalidation reference:** " + str(e.get("invalidation_reference")),
            "**Scheduled-event risk within 2h:** " + ("YES" if e.get("event_within_120_min") else "Not flagged in feed"),
            "**Why this alert:** " + str(e.get("reason")),
            "",
        ]
    asia=early.get("asian_risk_context") or {}
    if (asia.get("risk_off_corrob_by_closed_jpy_15m_30m") and
        any(e.get("label")=="JPY_STRENGTH" for e in clusters)):
        lines += [
            "### Asian equities corroboration (not an independent trade signal)",
            "**KOSPI dated daily CFD change:** " + str(asia.get("daily_reference_change_pct")) + "%",
            "**KOSPI reference day (Korea):** " + str(asia.get("reference_date_kst")),
            "**15m/30m JPY-strength cross count:** " + str(asia.get("jpy_strength_crosses_closed_15m_30m")),
            "**Data status:** " + str(asia.get("status")) + "; NOT a verified current KRX intraday quote.",
            "**Source:** https://tradingeconomics.com/south-korea/stock-market",
            "",
        ]
    lines += [
        "### Data limitations",
        "Closed-candle prices are reference data, not guaranteed executable quotes. "
        "An early warning is not a broker entry, stop-loss, profit target or prediction.",
        "The scanner excludes 5m signals and does not need any third-party API keys.",
        "",
        "[Full 11-pair scanner dashboard](https://github.com/" +
            os.environ.get("GITHUB_REPOSITORY", "vincenzosorlando9-svg/fx-tradingview-scanner") +
            "/blob/main/fx_scan_dashboard.json)",
        "",
        "<!-- fx-mobile-alert-key:" + key + " -->",
    ]
    return title, "\n".join(lines), key


def github_request(method, url, token, data=None):
    payload = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url, data=payload, method=method,
        headers={"Accept": "application/vnd.github+json",
                 "Authorization": "Bearer " + token,
                 "X-GitHub-Api-Version": "2022-11-28",
                 "User-Agent": "fx-no-key-early-research-alert",
                 **({"Content-Type": "application/json"} if payload else {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        info = exc.read().decode(errors="replace")[:1200]
        raise RuntimeError(f"GitHub Issues API HTTP {exc.code}: {info}") from exc


def publish_issue(events, early, now, repo, owner, token):
    title, body, key = render_issue(events, early, now)
    base = "https://api.github.com/repos/" + repo
    # Defensive duplicate check, in addition to persisted per-pair/cluster state.
    issues = github_request("GET", base + "/issues?state=all&per_page=100", token)
    marker = "fx-mobile-alert-key:" + key
    for issue in issues:
        if marker in issue.get("body", ""):
            return issue["html_url"], key, False
    issue = github_request("POST", base + "/issues", token, {
        "title": title, "body": body, "assignees": [owner]})
    assigned = [x.get("login") for x in issue.get("assignees", [])]
    if owner not in assigned:
        github_request("POST", base + "/issues/" + str(issue["number"]) + "/assignees",
                       token, {"assignees": [owner]})
    return issue["html_url"], key, True


def main():
    early = json.loads(EARLY_PATH.read_text(encoding="utf-8"))
    dashboard = json.loads(DASH_PATH.read_text(encoding="utf-8"))
    state = (json.loads(STATE_PATH.read_text(encoding="utf-8"))
             if STATE_PATH.exists() else seed_state())
    now = datetime.now(UTC)
    events, updated = evaluate(early, dashboard, state, now)
    if events:
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        token = os.environ.get("GITHUB_TOKEN", "")
        assignee = os.environ.get("FX_ALERT_ASSIGNEE", "")
        if not repo or not token or not assignee:
            raise RuntimeError("GitHub Actions repo/token/assignee required; no external key")
        url, key, created = publish_issue(events, early, now, repo, assignee, token)
        updated["last_issue"] = {"url": url, "at_utc": iso(now),
                                 "event_count": len(events), "newly_created": created}
        updated["recent_issue_keys"] = (updated.get("recent_issue_keys", []) + [key])[-100:]
        print("FX mobile early alert", "created" if created else "already exists", url)
    else:
        print("FX mobile alert: no NEW qualified event (or initial baseline / quiet / stale)")
    STATE_PATH.write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
