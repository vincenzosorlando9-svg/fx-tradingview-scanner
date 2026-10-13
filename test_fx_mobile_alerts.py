"""Offline tests for keyless GitHub Issue FX alert decisions; NO live Issues created."""
import copy
import unittest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from fx_mobile_alerts import (PAIRS, evaluate, quiet_hours, seed_state,
                              render_issue, alert_key)

UTC = timezone.utc
BASE = datetime(2026, 10, 12, 21, 30, tzinfo=UTC)  # Monday 5:30 PM EDT

def iso(dt):
    return dt.isoformat()

def datasets(now, directions=None, params=None):
    directions = directions or {}
    params = params or {}
    early = {
        "generated_at_utc": iso(now), "feed_valid": True, "quiet_hours": False,
        "status": "RESEARCH_ONLY_PARTIAL_MACRO", "pairs": []}
    dashboard = {
        "early_rotation_generated_at_utc": iso(now),
        "source_versions_match": True, "pairs": []}
    for pair in PAIRS:
        direction = directions.get(pair, "NONE")
        options = params.get(pair, {})
        close = options.get("close", 1.125 if pair == "EURUSD" else 150.0)
        if pair.endswith("JPY"):
            close = options.get("close", 158.50)
        e = {
            "pair": pair, "direction": direction,
            "stage": "EARLY_DIRECTIONAL_ROTATION" if direction != "NONE" else "WAIT",
            "research_rank_score": options.get("score", 0.90 if direction != "NONE" else 0),
            "pressure_evidence": {
                "direction": options.get("pressure_dir", direction),
                "score": options.get("pressure_score", 4 if direction != "NONE" else 0),
                "evidence": ["FOUR_BAR_LOWER_HIGHS"] if direction == "SELL" else ["FOUR_BAR_HIGHER_LOWS"],
            },
            "signal_timeframes": ["15m", "30m"], "excluded_timeframes": ["5m"],
            "latest_closed_m15_utc": iso(options.get("bar15", now - timedelta(minutes=15))),
            "latest_closed_m30_utc": iso(now - timedelta(minutes=30)),
            "latest_closed_m15": close,
            "execution_allowed": False,
            "watch_only": direction in ("BUY", "SELL"),
            "fresh_trigger": options.get("fresh_trigger", True),
            "direction_invalidation_reference": options.get("invalidation",
                       close - .001 if direction == "BUY" else close + .001),
            "event_within_120_min": False
        }
        early["pairs"].append(e)
        dashboard["pairs"].append({"pair": pair, "source_valid": True})
    return early, dashboard

class MobileAlertsTest(unittest.TestCase):
    def test_baseline_no_spam_and_new_15m_sell(self):
        a, d = datasets(BASE)
        events, state = evaluate(a, d, seed_state(), BASE)
        self.assertEqual(events, [])
        later = BASE + timedelta(minutes=5)
        a, d = datasets(later, {"USDCAD":"SELL"}, {
            "USDCAD":{"close":1.4278, "invalidation":1.4290}})
        events, state = evaluate(a, d, state, later)
        self.assertEqual([e["type"] for e in events], ["NEW_DIRECTION"])
        self.assertEqual(events[0]["pair"], "USDCAD")
        self.assertEqual(events[0]["direction"], "SELL")
        events, _ = evaluate(a, d, state, later)
        self.assertEqual(events, [])

    def test_opposite_watch_then_two_distinct_15m_closes_flip(self):
        _, state = evaluate(*datasets(BASE), seed_state(), BASE)
        t1 = BASE + timedelta(minutes=5)
        _, state = evaluate(*datasets(t1, {"EURUSD":"BUY"},
                              {"EURUSD":{"close":1.1170, "invalidation":1.1150}}),
                            state, t1)
        t2 = BASE + timedelta(minutes=10)
        # New 15m/30m SELL pressure, while above BUY structure invalidation.
        p = {"EURUSD":{"close":1.1160, "invalidation":1.1180,
                        "pressure_score":4, "bar15":BASE}}
        ev, state = evaluate(*datasets(t2, {"EURUSD":"SELL"}, p), state, t2)
        self.assertEqual([e["type"] for e in ev], ["OPPOSITE_WATCH"])
        self.assertEqual(state["pairs"]["EURUSD"]["bias"], "BUY")
        ev, state = evaluate(*datasets(t2 + timedelta(minutes=1),
                             {"EURUSD":"SELL"}, p), state, t2 + timedelta(minutes=1))
        self.assertEqual(ev, [])
        self.assertEqual(state["pairs"]["EURUSD"]["bias"], "BUY")
        t3 = BASE + timedelta(minutes=20)
        p["EURUSD"]["bar15"] = BASE + timedelta(minutes=15)
        ev, state = evaluate(*datasets(t3, {"EURUSD":"SELL"}, p), state, t3)
        self.assertEqual([e["type"] for e in ev], ["DIRECTION_CHANGED"])
        self.assertEqual(state["pairs"]["EURUSD"]["bias"], "SELL")

    def test_structural_invalidation_flips_immediately(self):
        _, state = evaluate(*datasets(BASE), seed_state(), BASE)
        t1 = BASE + timedelta(minutes=5)
        _, state = evaluate(*datasets(t1, {"EURUSD":"BUY"},
                             {"EURUSD":{"close":1.1170, "invalidation":1.1150}}), state, t1)
        t2 = BASE + timedelta(minutes=10)
        ev, state = evaluate(*datasets(t2, {"EURUSD":"SELL"},
                                  {"EURUSD":{"close":1.1148,"pressure_score":4}}), state, t2)
        self.assertEqual([x["type"] for x in ev], ["DIRECTION_CHANGED"])
        self.assertEqual(state["pairs"]["EURUSD"]["bias"], "SELL")

    def test_six_pair_usd_weakness_cluster(self):
        _, state = evaluate(*datasets(BASE), seed_state(), BASE)
        t1 = BASE + timedelta(minutes=5)
        dr = {"AUDUSD":"BUY", "NZDUSD":"BUY", "EURUSD":"BUY",
              "GBPUSD":"BUY", "USDJPY":"SELL", "USDCAD":"SELL"}
        ev, state = evaluate(*datasets(t1, dr), state, t1)
        self.assertEqual(sum(x["type"]=="NEW_DIRECTION" for x in ev), 6)
        usd = [x for x in ev if x["type"]=="CURRENCY_CLUSTER" and x["label"]=="USD_WEAKNESS"]
        self.assertEqual(len(usd),1)
        self.assertEqual(set(usd[0]["pairs"]), set(dr))
        title, body, _ = render_issue(ev,
            {"generated_at_utc":iso(t1)}, t1)
        self.assertIn("USD WEAKNESS", title)
        self.assertIn("NOT VERIFIED", body)
        ev2, _ = evaluate(*datasets(t1, dr), state, t1)
        self.assertFalse(ev2)

    def test_missing_or_stale_feed_never_flips_or_notifies(self):
        _, state = evaluate(*datasets(BASE), seed_state(), BASE)
        t1 = BASE + timedelta(minutes=5)
        a, d = datasets(t1, {"USDCAD":"SELL"})
        a["feed_valid"] = False
        ev, new = evaluate(a, d, state, t1)
        self.assertEqual(ev, [])
        self.assertEqual(new, state)
        a["feed_valid"] = True
        a["pairs"][-2]["latest_closed_m15_utc"] = iso(t1-timedelta(hours=2))
        ev, new = evaluate(a, d, state, t1)
        self.assertEqual(ev, [])
        self.assertEqual(new["pairs"]["USDCAD"]["bias"],"NONE")

    def test_unavailable_5m_does_not_affect_any_alert(self):
        _, baseline = evaluate(*datasets(BASE), seed_state(), BASE)
        t1 = BASE + timedelta(minutes=5)
        a, d = datasets(t1, {"USDCAD":"SELL"})
        expected, _ = evaluate(a, d, baseline, t1)
        altered = copy.deepcopy(a)
        altered["pairs"][9]["fake_m5_data"] = {"price":19.0, "signal":"BUY"}
        actual, _ = evaluate(altered, d, baseline, t1)
        self.assertEqual(expected, actual)

    def test_quiet_hours_and_no_delayed_catchup(self):
        self.assertTrue(quiet_hours(datetime(2026,10,16,19,0,tzinfo=UTC)))
        self.assertTrue(quiet_hours(datetime(2026,10,17,18,0,tzinfo=UTC)))
        self.assertTrue(quiet_hours(datetime(2026,10,18,21,0,tzinfo=UTC)))
        self.assertFalse(quiet_hours(datetime(2026,10,18,22,0,tzinfo=UTC)))
        t1 = datetime(2026,10,16,19,0,tzinfo=UTC)
        a,d = datasets(t1, {"USDCAD":"SELL"})
        ev, unchanged = evaluate(a,d,seed_state(),t1)
        self.assertEqual(ev, [])
        self.assertFalse(unchanged.get("initialized_at_utc"))

    def test_missing_consistent_versions_blocks_alert(self):
        _, baseline = evaluate(*datasets(BASE), seed_state(), BASE)
        t1 = BASE+timedelta(minutes=5)
        a,d = datasets(t1,{"USDCAD":"SELL"})
        d["early_rotation_generated_at_utc"] = iso(t1-timedelta(minutes=15))
        ev, unchanged = evaluate(a,d,baseline,t1)
        self.assertEqual(ev,[])
        self.assertEqual(unchanged,baseline)

if __name__ == "__main__":
    unittest.main()
