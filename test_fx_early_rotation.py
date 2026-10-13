"""Regression tests: 15m + 30m are the ONLY early FX signal timeframes.

7:06PM EDT Oct 12 has no closed 7:00-7:15 candle yet: no hindsight 5m
warning is allowed. At 7:16 the 15m sell rotation is observable; 30m
is corroborating/context and must not veto first rotation.
"""
import copy
import json
import unittest
from datetime import datetime
from pathlib import Path
from fx_early_rotation import run

FIXTURE=json.loads(Path("fx_15m30m_replay_oct12.json").read_text())

def at(stamp):
    return datetime.fromisoformat(stamp.replace("Z","+00:00"))

def row(report,pair):
    return next(x for x in report["pairs"] if x["pair"]==pair)

class EarlyMoveTests(unittest.TestCase):
    def test_706_does_not_peek_at_unclosed_15m_bar(self):
        report=run(FIXTURE,at=at("2026-10-12T23:06:00Z"),strict_freshness=False)
        aud=row(report,"AUDJPY")
        self.assertAlmostEqual(aud["latest_closed_m15"],110.349)
        self.assertNotEqual(aud["direction"],"SELL")
        self.assertEqual(report["jpy_cluster"]["jpy_strength_crosses"],0)
        self.assertEqual(aud["signal_timeframes"],["15m","30m"])
        self.assertEqual(aud["excluded_timeframes"],["5m"])

    def test_716_15m_direction_detected_no_5m(self):
        report=run(FIXTURE,at=at("2026-10-12T23:16:00Z"),strict_freshness=False)
        aud=row(report,"AUDJPY")
        self.assertEqual(aud["direction"],"SELL")
        self.assertAlmostEqual(aud["latest_closed_m15"],110.315)
        self.assertIn(aud["stage"],("EARLY_M15_M30_MOMENTUM","EARLY_DIRECTIONAL_ROTATION",
                                    "M15_DIRECTIONAL_CONTINUATION","EARLY_JPY_CLUSTER_ROTATION"))
        self.assertGreaterEqual(report["jpy_cluster"]["jpy_strength_crosses"],3)
        for pair in ("AUDJPY","NZDJPY","EURJPY","USDJPY"):
            self.assertEqual(report["jpy_cluster"]["pairs"][pair]["direction"],"JPY_STRENGTH")
        self.assertFalse(aud["execution_allowed"])

    def test_signal_uses_closed_m15_and_m30_not_unclosed_future(self):
        moment=at("2026-10-12T23:16:00Z")
        original=row(run(FIXTURE,at=moment,strict_freshness=False),"AUDJPY")
        modified=copy.deepcopy(FIXTURE)
        for tf,duration in (("M15",900),("M30",1800)):
            bars=modified["pairs"]["AUDJPY"]["tf"][tf]
            for i,t in enumerate(bars["t"]):
                if t-10800+duration>moment.timestamp():
                    bars["o"][i]=99.;bars["h"][i]=100.
                    bars["l"][i]=98.;bars["c"][i]=99.
        updated=row(run(modified,at=moment,strict_freshness=False),"AUDJPY")
        for key in ("direction","stage","latest_closed_m15","latest_closed_m30","pressure_evidence"):
            self.assertEqual(original.get(key),updated.get(key))

    def test_all_11_pairs_without_any_5m_feed(self):
        self.assertTrue(all("M5" not in entry["tf"] for entry in FIXTURE["pairs"].values()))
        report=run(FIXTURE,at=at("2026-10-12T23:31:00Z"),strict_freshness=False)
        self.assertEqual(len(report["pairs"]),11)
        self.assertEqual(report["jpy_cluster"]["signal_timeframes"],["15m","30m"])
        self.assertTrue(all(x.get("execution_allowed") is False for x in report["pairs"]))

    def test_friday_afternoon_quiet(self):
        out=run(FIXTURE,at=at("2026-10-16T19:00:00Z"),strict_freshness=False)
        self.assertTrue(out["quiet_hours"])
        self.assertEqual(out["top_five_early_priority"],[])

    def test_bad_source_clock_is_rejected(self):
        invalid=copy.deepcopy(FIXTURE)
        invalid["source_timestamp"]+=1800
        out=run(invalid,at=at("2026-10-12T23:31:00Z"),strict_freshness=False)
        self.assertFalse(out["feed_valid"])
        self.assertEqual(out["status"],"MISSING_OR_STALE_SOURCE")

if __name__=="__main__":
    unittest.main()
