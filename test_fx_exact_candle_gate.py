"""Exact M15/M30/H1 cadence tests with synthetic server +3h stamps."""
import unittest
from datetime import datetime, timedelta, timezone
from fx_exact_candle_gate import expected_slot,validate,market_open,PAIRS,TF_SECONDS
UTC=timezone.utc
def d(hour,minute):
    return datetime(2026,10,13,hour,minute,tzinfo=UTC)
def sample(now,slot_close,wrong=None,gap=None):
    from datetime import datetime
    server_offset=3*3600
    pairs={}
    for pair in PAIRS:
        frames={}
        for tf,seconds in TF_SECONDS.items():
            ending=slot_close.replace(tzinfo=UTC)
            ending=datetime.fromtimestamp((int(ending.timestamp())//seconds)*seconds,UTC)
            last=ending
            if wrong==(pair,tf):
                last-=timedelta(seconds=seconds)
            starts=[]
            for i in range(8):
                start=last-timedelta(seconds=seconds*(8-i))
                if gap==(pair,tf) and i==6: start-=timedelta(seconds=seconds)
                starts.append(start.timestamp()+server_offset)
            frames[tf]={"t":starts,"o":[100.0]*8,"h":[101.0]*8,
                        "l":[99.0]*8,"c":[100.5]*8}
        pairs[pair]={"tf":frames}
    return {"source_timestamp":now.timestamp()+server_offset,
            "collected_at_utc":(now-timedelta(seconds=3)).isoformat(),
            "pairs":pairs}

class ExactCandleGateTests(unittest.TestCase):
    def test_four_scan_targets_and_exact_tf_close_expectations(self):
        for minute,expected in [(2,(0,0,0)),(17,(15,0,0)),
                                (32,(30,30,0)),(47,(45,30,0))]:
            now=d(16,minute)+timedelta(seconds=10)
            slot=expected_slot(now)
            self.assertTrue(slot["accepting_new_scan"])
            self.assertEqual(slot["candle_slot_close_utc"],d(16,(minute-2)).isoformat())
            r=validate(sample(now,d(16,minute-2)),now)
            self.assertTrue(r["signal_publication_allowed"],(minute,r["missing"][:3]))
            self.assertEqual(r["validated_pairs"],11)
            self.assertEqual(tuple(int(r["expected_closes"][k][14:16]) for k in ("M15","M30","H1")),expected)

    def test_provider_late_one_m15_does_not_claim_success(self):
        now=d(16,17)+timedelta(seconds=10)
        r=validate(sample(now,d(16,15),wrong=("AUDJPY","M15")),now)
        self.assertEqual(r["status"],"WAIT_FOR_REQUIRED_CANDLES")
        self.assertFalse(r["signal_publication_allowed"])
        self.assertTrue(any("AUDJPY:M15" in s for s in r["missing"]))

    def test_missing_h1_is_blocked_even_if_m15_is_fresh(self):
        now=d(17,2)+timedelta(seconds=10)
        r=validate(sample(now,d(17,0),wrong=("AUDJPY","H1")),now)
        self.assertFalse(r["signal_publication_allowed"])
        self.assertTrue(any("AUDJPY:H1" in s for s in r["missing"]))

    def test_missing_m30_history_blocks_publication(self):
        now=d(16,32)+timedelta(seconds=10)
        r=validate(sample(now,d(16,30),gap=("EURUSD","M30")),now)
        self.assertFalse(r["signal_publication_allowed"])
        self.assertTrue(any("EURUSD:M30:NON_CONTIGUOUS" in s for s in r["missing"]))

    def test_schedule_delay_is_explicit(self):
        slot=expected_slot(d(16,9))
        self.assertEqual(slot["candle_slot_close_utc"],d(16,0).isoformat())
        self.assertFalse(slot["accepting_new_scan"])

    def test_weekend_market_close(self):
        self.assertFalse(market_open(datetime(2026,10,17,16,tzinfo=UTC)))
        self.assertTrue(market_open(datetime(2026,10,13,16,tzinfo=UTC)))

if __name__=="__main__":unittest.main()
