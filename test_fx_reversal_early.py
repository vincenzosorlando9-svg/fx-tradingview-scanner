"""USD/CAD 8:15 PM ET early rotation regression; only closed 15m/30m.

No 5m charts, no API keys, no lookahead and no fictitious trade execution.
"""
import copy
import json
import unittest
from datetime import datetime
from pathlib import Path
from fx_early_rotation import run

FIXTURE=json.loads(Path("fx_reversal_replay_oct12.json").read_text())
# Crucial: Strip out the legacy 5m chart, so the tests would fail if the
# live early detector silently depended on it.
FIXTURE["pairs"]["USDCAD"]["tf"].pop("M5",None)
def at(clock):
    return datetime.fromisoformat("2026-10-13T"+clock+":00+00:00")
def usdcad(out):
    return next(row for row in out["pairs"] if row["pair"]=="USDCAD")

class USDCADEarlyRotationTests(unittest.TestCase):
    def test_815_sell_watch_without_breakout(self):
        report=run(FIXTURE,at=at("00:15"),strict_freshness=False)
        row=usdcad(report)
        self.assertAlmostEqual(row["latest_closed_m15"],1.42816)
        self.assertEqual(row["direction"],"SELL")
        self.assertEqual(row["stage"],"EARLY_DIRECTIONAL_ROTATION")
        self.assertTrue(row["reversal_watch_no_break_required"])
        self.assertGreaterEqual(row["pressure_evidence"]["sell_evidence"],3)
        self.assertLessEqual(row["latest_closed_m15"],row["range_high"])
        self.assertGreaterEqual(row["latest_closed_m15"],row["range_low"])
        self.assertFalse(row["execution_allowed"])
        self.assertIn("USDCAD",[x["pair"] for x in report["top_five_early_priority"]])

    def test_830_and_845_green_candles_do_not_erase_watch(self):
        report=None
        for t in ("00:15","00:30","00:45"):
            report=run(FIXTURE,at=at(t),previous=report,strict_freshness=False)
        row=usdcad(report)
        self.assertEqual(row["direction"],"SELL")
        self.assertEqual(row["stage"],"EARLY_ROTATION_TRACKING")
        self.assertFalse(row["fresh_trigger"])
        episode=next(x for x in report["active_episodes"] if x["pair"]=="USDCAD")
        self.assertEqual(episode["first_observed_at_utc"],at("00:15").isoformat())
        self.assertFalse(episode["execution_allowed"])

    def test_9pm_bearish_followthrough_retains_first_815_warning(self):
        report=None
        for t in ("00:15","00:30","00:45","01:00"):
            report=run(FIXTURE,at=at(t),previous=report,strict_freshness=False)
        row=usdcad(report)
        self.assertEqual(row["direction"],"SELL")
        self.assertAlmostEqual(row["latest_closed_m15"],1.42779)
        episode=next(x for x in report["active_episodes"] if x["pair"]=="USDCAD")
        self.assertEqual(episode["first_observed_at_utc"],at("00:15").isoformat())
        self.assertFalse(episode["execution_allowed"])

    def test_future_15m30m_candles_cannot_change_815_warning(self):
        moment=at("00:15")
        orig=usdcad(run(FIXTURE,at=moment,strict_freshness=False))
        altered=copy.deepcopy(FIXTURE)
        for tf,duration in (("M15",900),("M30",1800)):
            bars=altered["pairs"]["USDCAD"]["tf"][tf]
            for i,t in enumerate(bars["t"]):
                if t-10800+duration>moment.timestamp():
                    bars["o"][i]=1.3;bars["h"][i]=1.31
                    bars["l"][i]=1.29;bars["c"][i]=1.3
        after=usdcad(run(altered,at=moment,strict_freshness=False))
        keys=("direction","stage","pressure_evidence","latest_closed_m15",
              "latest_closed_m30","range_low","range_high")
        self.assertEqual(tuple(orig.get(k) for k in keys),
                         tuple(after.get(k) for k in keys))

    def test_5m_data_cannot_modify_signal(self):
        moment=at("00:15")
        orig=usdcad(run(FIXTURE,at=moment,strict_freshness=False))
        altered=copy.deepcopy(FIXTURE)
        altered["pairs"]["USDCAD"]["tf"]["M5"]={
            "t":[1791835200,1791835500,1791835800,1791836100,1791836400],
            "o":[1.9]*5,"h":[2.0]*5,"l":[1.8]*5,"c":[1.9]*5
        }
        after=usdcad(run(altered,at=moment,strict_freshness=False))
        for field in ("direction","stage","pressure_evidence","research_rank_score"):
            self.assertEqual(orig.get(field),after.get(field))

    def test_flat_chop_does_not_trigger_reversal(self):
        moment=at("00:15")
        sample=copy.deepcopy(FIXTURE)
        for name,span in (("M15",900),("M30",1800)):
            f=sample["pairs"]["USDCAD"]["tf"][name]
            for i,t in enumerate(f["t"]):
                if t-10800+span<=moment.timestamp():
                    close=1.4281+(.00001 if i%2==0 else -.00001)
                    f["o"][i]=1.4281;f["h"][i]=1.4282
                    f["l"][i]=1.4280;f["c"][i]=close
        row=usdcad(run(sample,at=moment,strict_freshness=False))
        self.assertEqual(row["pressure_evidence"]["direction"],"NONE")
        self.assertEqual(row["direction"],"NONE")

if __name__=="__main__":
    unittest.main()
