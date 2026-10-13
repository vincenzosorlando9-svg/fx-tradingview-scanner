"""NZDJPY 10:45/11:00 PM Oct 12 pre-flip preview regression.

The prior SELL is *held* until invalidated; an earlier, separate BUY WATCH
is sent based solely on closed M15/M30 bars. No M5, no future bars, no orders.
"""
import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_early_rotation import run
from fx_mobile_alerts import evaluate, seed_state
from test_fx_mobile_alerts import datasets

VOL = json.loads(Path("fx_15m30m_replay_oct12.json").read_text())
def at(t):
    return datetime.fromisoformat("2026-10-13T"+t+":00+00:00")
def get(o,p="NZDJPY"):
    return next(x for x in o["pairs"] if x["pair"]==p)

def prior_sell():
    return {"active_episodes":[{
        "pair":"NZDJPY","direction":"SELL",
        "first_observed_at_utc":"2026-10-13T02:41:58+00:00",
        "last_observed_at_utc":"2026-10-13T02:57:46+00:00",
        "initial_closed_price":88.457,
        "latest_closed_price":88.464,
        "invalidation_reference":88.545,
        "research_rank_score":0.52
    }]}

class PreFlipReversalTests(unittest.TestCase):
    def test_1045_still_needs_m30_bullish_pressure(self):
        row = get(run(VOL,at=at("02:45"),strict_freshness=False))
        self.assertEqual(row["latest_closed_m15"],88.464)
        self.assertEqual(row["possible_opposite_rotation"]["direction"],"NONE")

    def test_1100_buy_watch_despite_held_sell(self):
        out=run(VOL,at=at("03:00"),previous=prior_sell(),strict_freshness=False)
        row=get(out)
        self.assertEqual(row["latest_closed_m15"],88.489)
        self.assertEqual(row["latest_closed_m30"],88.489)
        self.assertEqual(row["direction"],"SELL")
        self.assertEqual(row["stage"],"EARLY_ROTATION_TRACKING")
        cw=row["possible_opposite_rotation"]
        self.assertEqual(cw["direction"],"BUY")
        self.assertAlmostEqual(cw["two_m15_net_pips"],3.5)
        self.assertEqual(cw["first_detectable_closed_m15_utc"],at("03:00").isoformat())
        self.assertFalse(cw["execution_allowed"])
        self.assertTrue(cw["no_breakout_required"])

    def test_no_future_candles_can_trigger_1100_buy_watch(self):
        orig = get(run(VOL,at=at("03:00"),previous=prior_sell(),strict_freshness=False))
        altered=copy.deepcopy(VOL)
        for tf,dur in (("M15",900),("M30",1800)):
            f=altered["pairs"]["NZDJPY"]["tf"][tf]
            for i,t in enumerate(f["t"]):
                if t-10800+dur>at("03:00").timestamp():
                    f["c"][i]=90; f["o"][i]=89;f["h"][i]=91;f["l"][i]=88
        new = get(run(altered,at=at("03:00"),previous=prior_sell(),strict_freshness=False))
        for k in ("possible_opposite_rotation","direction","latest_closed_m15","latest_closed_m30"):
            self.assertEqual(orig[k],new[k])

    def test_iphone_watch_sent_before_main_buy_and_only_once(self):
        t0=at("02:55")
        a,d=datasets(t0,{"NZDJPY":"SELL"},
                     {"NZDJPY":{"close":88.464,"invalidation":88.545}})
        ev,st=evaluate(a,d,seed_state(),t0)
        self.assertEqual(ev,[])
        t1=at("03:00")
        a,d=datasets(t1,{"NZDJPY":"SELL"},
                     {"NZDJPY":{"close":88.489,"invalidation":88.545,"score":0.52}})
        z=get(a)
        z["possible_opposite_rotation"]={
           "direction":"BUY","evidence":["TWO_CONSECUTIVE_CLOSED_M15_HIGHER_CLOSES",
                                          "LAST_CLOSED_M30_POSITIVE"],
           "first_detectable_closed_m15_utc":t1.isoformat()}
        z["latest_closed_m15_utc"]=t1.isoformat()
        z["latest_closed_m30_utc"]=t1.isoformat()
        ev,st=evaluate(a,d,st,t1)
        watch=[x for x in ev if x["pair"]=="NZDJPY"]
        self.assertEqual([x["type"] for x in watch],["OPPOSITE_WATCH"])
        self.assertEqual(watch[0]["direction"],"BUY")
        self.assertEqual(watch[0]["previous"],"SELL")
        self.assertEqual(st["pairs"]["NZDJPY"]["bias"],"SELL")
        ev,st=evaluate(a,d,st,t1+timedelta(minutes=1))
        self.assertFalse([x for x in ev if x.get("pair")=="NZDJPY"])
        t2=at("03:33")
        a,d=datasets(t2,{"NZDJPY":"BUY"},
                     {"NZDJPY":{"close":88.549,"invalidation":88.409}})
        ev,st=evaluate(a,d,st,t2)
        self.assertEqual([x["type"] for x in ev if x.get("pair")=="NZDJPY"],
                         ["DIRECTION_CHANGED"])
        self.assertEqual(st["pairs"]["NZDJPY"]["bias"],"BUY")

if __name__=="__main__":
    unittest.main()
