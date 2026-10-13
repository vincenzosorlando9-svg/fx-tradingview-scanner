"""Historic USD/CAD 8:15 PM ET directional rotation regression.

Only closed historical OHLC bars; no future information or broker execution proof.
Replays alternate BUY/SELL pressure and protects an early reversal watch through
intermittent bullish candles, rather than forcing a breakout.
"""
import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from fx_early_rotation import (detect_pair, directional_pressure, pair_bars,
                              run, server_offset)

FIXTURE=json.loads(Path("fx_reversal_replay_oct12.json").read_text())
def at(clock):
    return datetime.fromisoformat("2026-10-13T"+clock+":00+00:00")
def usdcad(out):
    return next(row for row in out["pairs"] if row["pair"]=="USDCAD")

class USDCADEarlyRotationTests(unittest.TestCase):
    def test_815_warning_without_breakout_or_hourly_confirmation(self):
        now=at("00:15")
        result=run(FIXTURE,at=now,strict_freshness=False)
        row=usdcad(result)
        self.assertEqual(row["latest_closed_m15"],1.42816)
        self.assertEqual(row["direction"],"SELL")
        self.assertEqual(row["stage"],"EARLY_DIRECTIONAL_ROTATION")
        self.assertTrue(row["reversal_watch_no_break_required"])
        self.assertGreaterEqual(row["pressure_evidence"]["sell_evidence"],3)
        self.assertLessEqual(row["latest_closed_m5"],row["range_high"])
        self.assertGreaterEqual(row["latest_closed_m5"],row["range_low"])
        self.assertFalse(row["execution_allowed"])
        self.assertIn("USDCAD",[x["pair"] for x in result["top_five_early_priority"]])

    def test_830_and_845_bullish_candles_do_not_erase_815_watch(self):
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

    def test_recovered_sell_strength_9pm_after_first_815_watch(self):
        report=None
        for t in ("00:15","00:30","00:45","01:00"):
            report=run(FIXTURE,at=at(t),previous=report,strict_freshness=False)
        row=usdcad(report)
        self.assertEqual(row["direction"],"SELL")
        self.assertEqual(row["latest_closed_m15"],1.42779)
        episode=next(x for x in report["active_episodes"] if x["pair"]=="USDCAD")
        self.assertEqual(episode["first_observed_at_utc"],at("00:15").isoformat())
        self.assertFalse(episode["execution_allowed"])

    def test_future_candles_cannot_change_815_warning(self):
        moment=at("00:15")
        orig=usdcad(run(FIXTURE,at=moment,strict_freshness=False))
        modified=copy.deepcopy(FIXTURE)
        lengths={"M5":300,"M15":900,"M30":1800}
        for tf in ("M5","M15","M30"):
            bars=modified["pairs"]["USDCAD"]["tf"][tf]
            for i,t in enumerate(bars["t"]):
                if t-10800+lengths[tf]>moment.timestamp():
                    bars["o"][i]=1.3
                    bars["h"][i]=1.31
                    bars["l"][i]=1.29
                    bars["c"][i]=1.3
        after=usdcad(run(modified,at=moment,strict_freshness=False))
        keys=("direction","stage","pressure_evidence","latest_closed_m15",
              "latest_closed_m5","range_low","range_high")
        self.assertEqual(tuple(orig.get(k) for k in keys),
                         tuple(after.get(k) for k in keys))

    def test_chop_does_not_emit_an_early_reversal_without_evidence(self):
        now=at("00:15")
        sample=copy.deepcopy(FIXTURE)
        p=sample["pairs"]["USDCAD"]["tf"]
        for name,span in (("M5",300),("M15",900),("M30",1800)):
            f=p[name]
            for i,t in enumerate(f["t"]):
                if (t-10800+span)<=now.timestamp():
                    close=1.4281+(.00001 if i%2==0 else -.00001)
                    f["o"][i]=1.4281
                    f["h"][i]=1.4282
                    f["l"][i]=1.4280
                    f["c"][i]=close
        row=usdcad(run(sample,at=now,strict_freshness=False))
        self.assertEqual(row["pressure_evidence"]["direction"],"NONE")
        self.assertEqual(row["direction"],"NONE")

if __name__=="__main__":
    unittest.main()
