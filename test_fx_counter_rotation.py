"""Closed 15m/30m pre-flip research watch regression.

The historical Oct 12 replay was collected at 21:05 ET; it cannot verify
22:45-23:00 ET candles. NEVER use that fixture to claim an 11 PM signal.
Use explicit synthetic CLOSED candles for unit tests instead.
GitHub Issue notification publication remains DISABLED in the workflow.
"""
import unittest
from datetime import datetime, timedelta, timezone

from fx_early_rotation import counter_rotation_watch
from fx_mobile_alerts import evaluate, seed_state
from test_fx_mobile_alerts import datasets


def at(t):
    return datetime.fromisoformat("2026-10-13T"+t+":00+00:00")


def bar(t, close, low, high):
    return {"close_utc":at(t).isoformat(), "c":close, "l":low, "h":high,
            "o":close}


def synthetic_closed_bars():
    # These values are deliberately fabricated TEST DATA, not market history.
    m15=[
        bar("02:00",88.400,88.385,88.415),
        bar("02:15",88.405,88.390,88.420),
        bar("02:30",88.410,88.395,88.425),
        bar("02:45",88.415,88.400,88.430),
        bar("03:00",88.435,88.420,88.450),
    ]
    m30=[
        bar("02:00",88.425,88.390,88.445),
        bar("02:30",88.410,88.390,88.430),
        bar("03:00",88.435,88.400,88.450),
    ]
    return m15,m30


class PreFlipReversalTests(unittest.TestCase):
    def test_early_watch_not_triggered_by_unconfirmed_30m(self):
        m15,m30=synthetic_closed_bars()
        watch=counter_rotation_watch("NZDJPY",{"M15":m15[:4],"M30":m30[:2]})
        self.assertEqual(watch["direction"],"NONE")

    def test_two_closed_15m_and_positive_30m_watch_only(self):
        m15,m30=synthetic_closed_bars()
        watch=counter_rotation_watch("NZDJPY",{"M15":m15,"M30":m30})
        self.assertEqual(watch["direction"],"BUY")
        self.assertAlmostEqual(watch["two_m15_net_pips"],2.5)
        self.assertEqual(watch["first_detectable_closed_m15_utc"],at("03:00").isoformat())
        self.assertFalse(watch["execution_allowed"])
        self.assertTrue(watch["no_breakout_required"])

    def test_one_watch_without_flipping_original_bias(self):
        t0=at("02:55")
        a,d=datasets(t0,{"NZDJPY":"SELL"},
                     {"NZDJPY":{"close":88.410,"invalidation":88.550}})
        ev,st=evaluate(a,d,seed_state(),t0)
        self.assertEqual(ev,[])
        t1=at("03:00")
        a,d=datasets(t1,{"NZDJPY":"SELL"},
                     {"NZDJPY":{"close":88.435,"invalidation":88.550,"score":0.52}})
        z=next(x for x in a["pairs"] if x["pair"]=="NZDJPY")
        z["possible_opposite_rotation"]={
            "direction":"BUY","evidence":["TWO_CONSECUTIVE_CLOSED_M15_HIGHER_CLOSES",
                                           "LAST_CLOSED_M30_POSITIVE"],
            "first_detectable_closed_m15_utc":t1.isoformat()}
        z["latest_closed_m15_utc"]=t1.isoformat()
        z["latest_closed_m30_utc"]=t1.isoformat()
        ev,st=evaluate(a,d,st,t1)
        watch=[x for x in ev if x.get("pair")=="NZDJPY"]
        self.assertEqual([x["type"] for x in watch],["OPPOSITE_WATCH"])
        self.assertEqual(watch[0]["direction"],"BUY")
        self.assertEqual(st["pairs"]["NZDJPY"]["bias"],"SELL")
        ev,st=evaluate(a,d,st,t1+timedelta(minutes=1))
        self.assertFalse([x for x in ev if x.get("pair")=="NZDJPY"])

    def test_main_direction_changes_only_after_original_invalidation(self):
        t0=at("02:55")
        a,d=datasets(t0,{"NZDJPY":"SELL"},
                     {"NZDJPY":{"close":88.410,"invalidation":88.550}})
        _,st=evaluate(a,d,seed_state(),t0)
        t1=at("03:15")
        a,d=datasets(t1,{"NZDJPY":"BUY"},
                     {"NZDJPY":{"close":88.560,"invalidation":88.420}})
        ev,st=evaluate(a,d,st,t1)
        self.assertEqual([x["type"] for x in ev if x.get("pair")=="NZDJPY"],
                         ["DIRECTION_CHANGED"])
        self.assertEqual(st["pairs"]["NZDJPY"]["bias"],"BUY")


if __name__=="__main__":
    unittest.main()
