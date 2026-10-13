"""No-key static Trading Economics KOSPI parser correctness & stale safeguards."""
import unittest
from datetime import datetime, timezone
from fx_asian_risk_collector import parse_page, MAX_REFERENCE_DAYS

UTC=timezone.utc
PAGE="""<html><head><title>South Korea Stock Market - Quote</title></head><body>
<h1>South Korea Stock Market</h1>
<div>Actual</div><div>6384</div><div>Daily Change</div><div>-3.65%</div>
<h2>South Korea Stock Market - Summary</h2>
<p>The benchmark KOSPI plunged more than 6% to around 5,990 on Tuesday.</p>
<h3>South Korea Stock Market - Stats</h3>
<p>South Korea's main stock market index, the KOSPI, fell to 6384 points
on October 12, 2026, losing 3.65% from the previous session.</p>
<div>News Stream</div>
<h3>South Korean Shares Plunge to Over 2-Month Low</h3>
<p>The KOSPI plunged more than 6% to around 5990 on Tuesday.</p><p>2026-10-13</p>
</body></html>"""

class KOSPINoKeyTests(unittest.TestCase):
    def test_daily_reference_not_headline_intraday_quote(self):
        row=parse_page(PAGE,datetime(2026,10,13,3,15,tzinfo=UTC))
        self.assertEqual(row["daily_reference_level"],6384)
        self.assertAlmostEqual(row["daily_reference_change_pct"],-3.65)
        self.assertEqual(row["reference_date_kst"],"2026-10-12")
        self.assertEqual(row["risk_tier_from_daily_reference"],"SEVERE_DAILY_RISK_OFF")
        self.assertEqual(row["daily_reference_status"],"DATED_PUBLIC_DAILY_CFD_REFERENCE")
        self.assertFalse(row["verified_intraday_quote"])
        self.assertIsNone(row["source_quote_timestamp_utc"])
        self.assertEqual(row["intraday_news_date"],"2026-10-13")
        self.assertIn("South Korean Shares Plunge",row["intraday_news_summary"])
        self.assertTrue(row["news_is_quote"] is False)

    def test_reference_outdated_does_not_support_live_macro_risk(self):
        row=parse_page(PAGE,datetime(2026,10,20,3,15,tzinfo=UTC))
        self.assertEqual(row["status"],"PARTIAL_NEWS_ONLY")
        self.assertEqual(row["risk_tier_from_daily_reference"],"UNAVAILABLE")
        self.assertEqual(row["daily_reference_status"],"STALE_OR_FUTURE_DATED")

    def test_failed_fetch_or_changed_page_does_not_invent_index(self):
        row=parse_page("<html>Anti-bot blocked</html>",datetime(2026,10,13,3,15,tzinfo=UTC))
        self.assertEqual(row["status"],"UNAVAILABLE")
        self.assertIsNone(row["daily_reference_level"])
        self.assertIsNone(row["daily_reference_change_pct"])

    def test_headline_must_not_become_numeric_quote(self):
        page=PAGE.replace("<div>Actual</div><div>6384</div><div>Daily Change</div><div>-3.65%</div>","")
        row=parse_page(page,datetime(2026,10,13,3,15,tzinfo=UTC))
        self.assertIsNone(row["daily_reference_level"])
        self.assertIsNone(row["daily_reference_change_pct"])
        self.assertEqual(row["risk_tier_from_daily_reference"],"UNAVAILABLE")

    def test_script_tags_cannot_inject_quote(self):
        page=PAGE.replace("<div>Actual</div><div>6384</div><div>Daily Change</div><div>-3.65%</div>",
            "<script>Actual 9999 Daily Change 9.99%</script>")
        row=parse_page(page,datetime(2026,10,13,3,15,tzinfo=UTC))
        self.assertIsNone(row["daily_reference_level"])
        self.assertIsNone(row["daily_reference_change_pct"])

if __name__=="__main__":
    unittest.main()
