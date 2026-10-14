import importlib.util
import pathlib
import unittest
from datetime import datetime,timezone,timedelta
ROOT=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location("fxquotes",ROOT/"quotes.py")
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
NOW=datetime(2026,10,14,15,0,tzinfo=timezone.utc)
def q(source,bid=1.1000,ask=1.1002,observed_at=None,pair="EURUSD"):
    return {"pair":pair,"source":source,"bid":bid,"ask":ask,"observed_at":(observed_at or NOW).isoformat()}
class QuoteTests(unittest.TestCase):
    def test_all_pairs(self):
        self.assertEqual(len(mod.PAIRS),11)
        self.assertEqual(mod.pip_size("USDJPY"),0.01)
        self.assertEqual(mod.pip_size("EURUSD"),0.0001)
    def test_fresh_quote(self):
        self.assertTrue(mod.validate_quote(q("a"),now=NOW)[0])
    def test_stale_quote(self):
        self.assertEqual(mod.validate_quote(q("a",observed_at=NOW-timedelta(minutes=10)),now=NOW)[1],"stale_quote")
    def test_future_quote(self):
        self.assertEqual(mod.validate_quote(q("a",observed_at=NOW+timedelta(minutes=1)),now=NOW)[1],"future_timestamp")
    def test_spread_inversion(self):
        self.assertEqual(mod.validate_quote(q("a",bid=1.2,ask=1.1),now=NOW)[1],"invalid_bid_ask")
    def test_one_source_not_enough(self):
        self.assertEqual(mod.reconcile_quotes([q("a")],now=NOW)["pairs"]["EURUSD"]["status"],"UNAVAILABLE")
    def test_disagreement(self):
        result=mod.reconcile_quotes([q("a"),q("b",bid=1.101,ask=1.1012)],now=NOW)
        self.assertEqual(result["pairs"]["EURUSD"]["status"],"CONFLICT")
    def test_consistency_does_not_enable_trading(self):
        result=mod.reconcile_quotes([q("a"),q("b")],now=NOW)
        self.assertEqual(result["pairs"]["EURUSD"]["status"],"STRUCTURALLY_CONSISTENT")
        self.assertIs(result["trading_evidence_gate_pass"],False)
if __name__=="__main__":unittest.main()
