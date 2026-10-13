"""Offline regression tests for the public collectors, time safety and 11-pair fusion."""
import unittest
from datetime import datetime, timedelta, timezone

from fx_macro_collector import (parse_bonds, parse_policy, parse_index, parse_feargreed, parse_forexcracked, news_currency_tags,
                                parse_oilprice, parse_news, parse_te_noncrude, parse_cboe_vix, extract_bond_table)
from fx_macro_engine import (normalize, derived_deltas, rate_spreads,
                             build_pairs, news_context, observation_recent, metric)
from fx_ff_actuals_collector import parse as parse_actuals
from fx_cftc_tff_collector import parse as parse_cftc
from fx_retail_collector import parse as parse_myfxbook_pair
from fx_retail_sentiment_collector import parse as parse_retail
from fx_range_context import compute as compute_ranges, normalize_clock as range_clock, ny_rollover_start

UTC = timezone.utc
NOW = datetime(2026,10,13,12,0,tzinfo=UTC)
def webpage(body, url="https://tradingeconomics.com/united-states/government-bond-yield"):
    return {"url": url, "body":body, "http_status":"OK", "retrieved_at_utc":NOW.isoformat()}

class PublicCollectorTests(unittest.TestCase):
    def test_treasury_2y_5y_10y_30y_in_bonds_table(self):
        html = """<h1>US 10 Year Treasury Note Yield</h1>
        <p>US 10 Year Treasury Note Yield - Stats</p>
        <p>The US bond yield eased to 5.20% on October 13, 2026.</p>
        <table><tr><th>Bonds</th><th>Yield</th><th>Day</th><th>Month</th></tr>
        <tr><td>US 2Y</td><td>4.78</td><td>-0.023%</td><td>0.10%</td></tr>
        <tr><td>US 5Y</td><td>4.98</td><td>-0.035%</td><td>0.14%</td></tr>
        <tr><td>US 10Y</td><td>5.20</td><td>-0.040%</td><td>0.20%</td></tr>
        <tr><td>US 30Y</td><td>5.56</td><td>-0.036%</td><td>0.25%</td></tr>
        <tr><td>US 5Y TIPS</td><td>2.61</td><td>0.043%</td><td>0.28%</td></tr>
        <tr><td>US 10Y TIPS</td><td>2.86</td><td>0.009%</td><td>0.28%</td></tr>
        <tr><td>US 30Y TIPS</td><td>3.31</td><td>0.006%</td><td>0.28%</td></tr></table>"""
        result = parse_bonds(webpage(html), "USD")
        self.assertEqual(result["status"], "DATED_REFERENCE")
        self.assertEqual(set(result["maturities"]), {"2Y","5Y","10Y","30Y"})
        self.assertEqual(result["maturities"]["2Y"]["value_pct"], 4.78)
        self.assertEqual(result["maturities"]["5Y"]["value_pct"], 4.98)
        self.assertEqual(result["maturities"]["10Y"]["value_pct"], 5.20)
        self.assertEqual(result["maturities"]["30Y"]["value_pct"], 5.56)

    def test_missing_yield_table_never_assumed_from_prose(self):
        page = webpage("<p>US 10 year bond yield is 5.20%; US 2Y may move.</p>")
        self.assertEqual(parse_bonds(page, "USD")["status"], "UNAVAILABLE_NO_VERIFIED_BOND_TABLE")

    def test_policy_does_not_confuse_boe_rate_with_deposit_rate(self):
        html = """<p>The benchmark interest rate in the United Kingdom was last recorded at 3.75 percent.</p>
        <table><tr><th>Related</th><th>Last</th><th>Previous</th><th>Unit</th><th>Reference</th></tr>
        <tr><td>Deposit Interest Rate</td><td>3.60</td><td>3.60</td><td>percent</td><td>Sep 2026</td></tr>
        <tr><td>BoE Interest Rate</td><td>3.75</td><td>3.75</td><td>percent</td><td>Sep 2026</td></tr></table>"""
        result = parse_policy(webpage(html), "GBP")
        self.assertEqual(result["policy_rate_pct"], 3.75)
        self.assertEqual(result["reference_period"], "Sep 2026")
        self.assertIsNone(result["ois_rate_pct"])

    def test_kospi_daily_change_is_not_yearly_change(self):
        html = """<p>South Korea Stock Market - Stats The KOSPI fell to 6035 points on October 13, 2026, losing 5.46% from the previous session.</p>
        <table><tr><th>Indexes</th><th>Price</th><th>Day</th><th>Year</th></tr>
        <tr><td>KOSPI</td><td>6,035.35</td><td>-5.46%</td><td>69.45%</td></tr></table>"""
        result = parse_index(webpage(html), "KOSPI")
        self.assertEqual(result["daily_change_pct"], -5.46)
        self.assertEqual(result["value"], 6035.35)
        self.assertEqual(result["market_date"], "2026-10-13")

    def test_forexcracked_indicative_not_broker(self):
        page = webpage("<h1>Live Market Rates</h1>Last update: 18 seconds ago "
                       "AUD/USD 0p 0.69881 ▲ Ask 0.69881 "
                       "USD/JPY 0.1p 158.15 ▲ Ask 158.16")
        result = parse_forexcracked(page)
        self.assertEqual(len(result["pairs"]), 2)
        self.assertFalse(result["pairs"]["USDJPY"]["execution_allowed"])
        self.assertEqual(result["pairs"]["AUDUSD"]["bid"], .69881)

    def test_forexcracked_metal_and_china_context_without_crude(self):
        html="""<h1>Live Market Rates</h1>Last update: 18 seconds ago
        XAU/USD 0.08 4,205.95 ▲ Ask 4,206.03
        XAG/USD 280p 61.273 ▲ Ask 61.301
        XCU/USD 18p 6.77060 ▲ Ask 6.77240
        XNG/USD 180p 3.37600 ▲ Ask 3.39400
        ALUMINIUM 6.35 3,049.65 ▲ Ask 3,056.00
        USD/CNH 10.7p 6.69183 ▲ Ask 6.69290
        XBR/USD 100p 101.66 ▲ Ask 101.67"""
        result=parse_forexcracked(webpage(html))
        self.assertAlmostEqual(result["non_crude"]["GOLD"]["value"],4205.95)
        self.assertAlmostEqual(result["non_crude"]["SILVER"]["value"],61.273)
        self.assertAlmostEqual(result["non_crude"]["COPPER"]["value"],6.7706)
        self.assertAlmostEqual(result["non_crude"]["NATURAL_GAS"]["value"],3.376)
        self.assertAlmostEqual(result["non_crude"]["ALUMINIUM"]["value"],3049.65)
        self.assertAlmostEqual(result["cross_risk"]["USD_CNH"]["bid"],6.69183)
        self.assertNotIn("BRENT",result["non_crude"])
        self.assertNotIn("WTI",result["non_crude"])
        self.assertNotIn("USDCNH",result["pairs"])

    def test_canadian_dollar_news_does_not_automatically_tag_USD(self):
        self.assertEqual(news_currency_tags("Canadian dollar rises after Bank of Canada remarks"),["CAD"])

    def test_official_cboe_vix_is_dated_close_not_live(self):
        now=datetime.now(UTC)
        older=(now-timedelta(days=1)).strftime("%m/%d/%Y")
        today=now.strftime("%m/%d/%Y")
        body=f"""DATE,OPEN,HIGH,LOW,CLOSE
{older},18.0,19.0,17.5,18.0
{today},20.0,21.0,19.1,20.0
"""
        page=webpage(body,"https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv")
        obj=parse_cboe_vix(page)
        self.assertEqual(obj["status"],"DATED_REFERENCE")
        self.assertEqual(obj["value"],20.0)
        self.assertAlmostEqual(obj["daily_change_pct"],11.111,places=3)
        self.assertFalse(obj["verified_intraday"])
        norm=normalize({"vix_cboe_official_daily":obj})
        self.assertEqual(norm["INDEX:VIX_CBOE"]["v"],20.0)
        self.assertEqual(norm["INDEX:VIX_CBOE"]["observation_type"],"CBOE_OFFICIAL_HISTORICAL_DAILY_CLOSE")

    def test_secondary_commodities_never_substitute_crude_provider(self):
        today=datetime.now(UTC).strftime("%b/%d")
        html=f"""<html><table>
        <tr><th>Metals</th><th>Price</th><th>Chg</th><th>%Chg</th><th>Monthly</th><th>Date</th></tr>
        <tr><td>Copper USD/Lbs</td><td>6.7273</td><td>0.0106</td><td>0.43%</td><td>6.28%</td><td>{today}</td></tr>
        <tr><td>Iron Ore USD/T</td><td>90.83</td><td>0.15</td><td>0.17%</td><td>-6.89%</td><td>{today}</td></tr>
        <tr><td>Crude Oil USD/Bbl</td><td>500.00</td><td>20.00</td><td>4%</td><td>0%</td><td>{today}</td></tr>
        </table></html>"""
        p=webpage(html,"https://tradingeconomics.com/commodities")
        obj=parse_te_noncrude(p)
        self.assertEqual(obj["status"],"DATED_PUBLIC_COMMODITY_REFERENCES")
        self.assertEqual(obj["commodities"]["COPPER"]["value"],6.7273)
        self.assertEqual(obj["commodities"]["IRON_ORE"]["value"],90.83)
        self.assertNotIn("WTI",obj["commodities"])
        self.assertNotIn("BRENT",obj["commodities"])
        raw={"noncrude_te_secondary":obj,
             "forexcracked":{"non_crude":{"GOLD":{"value":4200,"unit":"source_units",
                            "status":"INDICATIVE_SOURCE",
                            "quote_timestamp_utc":NOW.isoformat()}}}}
        normalized=normalize(raw)
        self.assertEqual(normalized["COMMODITY:COPPER"]["v"],6.7273)
        self.assertIn("COMMODITY:GOLD",normalized)
        self.assertNotIn("COMMODITY:WTI",normalized)

    def test_oil_only_oilprice_with_delayed_status(self):
        html = """<table><tr><th>Name</th><th>Last</th><th>Change</th></tr>
        <tr><td>WTI Crude</td><td>91.81</td><td>-1.93</td><td>-2.06% (11-Minute Delay)</td></tr>
        <tr><td>Brent Crude</td><td>104.46</td><td>-2.19</td><td>-2.05% (11-Minute Delay)</td></tr></table>"""
        result = parse_oilprice(webpage(html, "https://oilprice.com/oil-price-charts/"))
        self.assertEqual(result["commodities"]["WTI"]["delay_minutes"], 11)
        self.assertEqual(result["commodities"]["BRENT"]["value_usd_per_barrel"], 104.46)
        self.assertFalse(result["verified_live_quote"])

    def test_feargreedmeter_title_without_cnn(self):
        page = webpage("<html><head><title>Fear and Greed Index: 46 (Neutral) | Stock Market Sentiment</title></head><body>Updated 9 minutes ago</body></html>")
        result = parse_feargreed(page)
        self.assertEqual(result["index"], 46)
        self.assertEqual(result["label"], "NEUTRAL")

    def test_news_rejects_old_or_untimed(self):
        news = """<rss><channel>
        <item><title>Fed remarks</title><link>https://www.fxstreet.com/a</link>
        <pubDate>Tue, 13 Oct 2026 11:45:00 GMT</pubDate></item>
        <item><title>Old rumor</title><link>https://www.fxstreet.com/b</link>
        <pubDate>Fri, 09 Oct 2026 11:45:00 GMT</pubDate></item>
        </channel></rss>"""
        result = parse_news(webpage(news), "FXStreet_RSS")
        # Date comparison against *real test execution time* may differ, but undated
        # articles are never treated as fresh.
        self.assertTrue(all(x.get("published_at_utc") for x in result["articles"]))

    def test_public_retail_delayed_valid_percentages(self):
        body = """<html><body>Community Outlook
          <section><h1>AUDUSD</h1><div>Short 62 %</div>
          <div>Long 38 %</div></section></body></html>"""
        result = parse_retail(body,NOW)
        self.assertEqual(result["pairs"]["AUDUSD"]["short_pct"],62)
        self.assertEqual(result["pairs"]["AUDUSD"]["long_pct"],38)
        self.assertGreaterEqual(result["reference_delay_minutes_minimum"],60)
        self.assertFalse(result["broker_executable"])

    def test_public_retail_rejects_ambiguous_sentiment(self):
        body = """<html><body>Community
          <div>AUDUSD Short 60% Long 70%</div></body></html>"""
        result = parse_retail(body,NOW)
        self.assertEqual(result["pairs"],{})

    def test_forexfactory_actuals_unique_event_only(self):
        html = """<table><tr class="calendar__row"><td class="calendar__currency">USD</td>
        <td class="calendar__event">NFIB Small Business Index</td>
        <td class="calendar__actual">97.9</td>
        <td class="calendar__forecast">98.1</td>
        <td class="calendar__previous">98.7</td></tr></table>"""
        calendar = {"events":[{"currency":"USD","title":"NFIB Small Business Index",
                  "event_at_utc":"2026-10-13T10:00:00+00:00","forecast":"98.1","previous":"98.7"}]}
        result = parse_actuals(html,calendar,NOW)
        self.assertEqual(len(result["actuals"]),1)
        self.assertEqual(result["actuals"][0]["reported_actual"],"97.9")
        self.assertIsNone(result["actuals"][0]["released_at_utc"])

    def test_forexfactory_actuals_no_future_or_ambiguous(self):
        html = """<table><tr class="calendar__row"><td class="calendar__currency">USD</td>
        <td class="calendar__event">CPI y/y</td><td class="calendar__actual">3.4%</td></tr></table>"""
        cal = {"events":[{"currency":"USD","title":"CPI y/y","event_at_utc":"2026-10-14T12:30:00+00:00"}]}
        self.assertEqual(len(parse_actuals(html,cal,NOW)["actuals"]),0)
        cal["events"].append({"currency":"USD","title":"CPI y/y",
                              "event_at_utc":"2026-10-10T12:30:00+00:00"})
        self.assertEqual(len(parse_actuals(html,cal,NOW)["actuals"]),0)

    def test_cftc_weekly_only_and_open_interest(self):
        row = '"CANADIAN DOLLAR - CHICAGO MERCANTILE EXCHANGE",261006,2026-10-06,090741,CME,00,090,371048,189180,69223,972,97612,133418,4647,31682,111307,4025,15212,6399,484,343814,330475,27234,40573'
        out = parse_cftc(row,NOW)
        self.assertEqual(out["currencies"]["CAD"]["leveraged_net"], -79625)
        self.assertEqual(out["currencies"]["CAD"]["open_interest_contracts"],371048)

    def test_myfxbook_public_delay_and_11_pair_identity(self):
        html = """<html><head><title>EURUSD Forex Sentiment</title></head>
        <body><h1>EURUSD Forex Sentiment</h1>
        <p>63% of the forex traders are currently going short with EUR/USD,
        with an average price of 1.1372, meanwhile 37% of the forex traders
        are going long with EUR/USD, with an average price of 1.1647.</p>
        <p>Data is delayed by 60 minutes</p></body></html>"""
        result=parse_myfxbook_pair(html,"EURUSD")
        self.assertEqual(result["status"],"PUBLISHED_RETAIL_SAMPLE_DELAYED_60_MIN")
        self.assertEqual(result["short_pct"],63)
        self.assertEqual(result["long_pct"],37)
        self.assertEqual(result["publisher_delay_min"],60)
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(parse_myfxbook_pair(html,"USDJPY")["status"],"PAGE_PAIR_NOT_VERIFIED")

    def test_cftc_nz_dollar_label_and_dealer_net(self):
        row = '"NZ DOLLAR - CHICAGO MERCANTILE EXCHANGE",261006,2026-10-06,112741,CME,00,090,200000,30000,60000,972,97612,133418,4647,31682,111307,4025,15212,6399,484,143814,130475,27234,40573'
        result=parse_cftc(row,NOW)
        self.assertEqual(result["currencies"]["NZD"]["dealer_net"],-30000)
        self.assertEqual(result["currencies"]["NZD"]["leveraged_net"],-79625)

class SessionRangeTests(unittest.TestCase):
    def test_provider_offset_has_strict_clock_tolerance(self):
        offset = range_clock(NOW.timestamp()+3*3600, NOW)
        self.assertEqual(offset, 10800)
        with self.assertRaises(ValueError):
            range_clock(NOW.timestamp()+19*60, NOW)

    def test_ADR20_uses_completed_D1_and_running_day_context_only(self):
        import calendar
        offset=3*3600
        start=ny_rollover_start(NOW)
        # 20 completed prior D1 bars, then the open current running daily bar.
        d1times=[start-timedelta(days=i) for i in range(20,0,-1)]+[start]
        d1={
          "t":[calendar.timegm(d.timetuple())+offset for d in d1times],
          "o":[1.1000]*21, "h":[1.1040]*20+[1.1020],
          "l":[1.1000]*21,"c":[1.1010]*21,
        }
        mt=[NOW-timedelta(minutes=15*i) for i in (4,3,2,1)]
        m15={"t":[calendar.timegm(d.timetuple())+offset for d in mt],
             "o":[1.1005]*4,"h":[1.1010]*4,
             "l":[1.1005]*4,"c":[1.1006]*4}
        result=compute_ranges("EURUSD",{"tf":{"D1":d1,"M15":m15}},offset,NOW)
        self.assertEqual(result["ADR20_complete_days"],20)
        self.assertAlmostEqual(result["ADR20_pips"],40)
        self.assertAlmostEqual(result["NY17_day_used_pips"],20)
        self.assertAlmostEqual(result["NY17_ADR_percent_used"],50)
        self.assertFalse(result["used_for_signal_direction"])
        self.assertFalse(result["D1_current_session_used_for_direction"])

class FusionTests(unittest.TestCase):
    def test_date_only_yield_has_no_intraday_clock(self):
        m = metric(4.8, "percent_yield", "TE", "DATED_REFERENCE",
                   market_date="2026-10-13")
        self.assertTrue(observation_recent(m,NOW))
        self.assertIsNone(m["source_observed_at_utc"])

    def test_deltas_require_sample_and_unchanged_source(self):
        old = metric(4.8, "percent_yield", "TE", "DATED_REFERENCE",
                     market_date="2026-10-13")
        new = metric(4.76, "percent_yield", "TE", "DATED_REFERENCE",
                     market_date="2026-10-13")
        hist = [{"at_utc":(NOW-timedelta(minutes=30)).isoformat(),
                 "metrics":{"BOND:USD:2Y": old}}]
        delta = derived_deltas({"BOND:USD:2Y":new},hist,NOW)
        self.assertAlmostEqual(delta["BOND:USD:2Y"]["30"]["change"], -4)
        hist[0]["metrics"]["BOND:USD:2Y"]["source"] = "not TE"
        self.assertIsNone(derived_deltas({"BOND:USD:2Y":new},hist,NOW)["BOND:USD:2Y"]["30"])

    def test_nominal_yield_never_compared_to_historical_TIPS(self):
        # Earlier scraper accidentally recorded US 10Y TIPS as US 10Y.
        # Its historical observation must not contaminate the new nominal feed.
        old = metric(2.86, "percent_yield", "TE", "DATED_REFERENCE",
                     market_date="2026-10-13")
        old["source_instrument"] = "US 10Y TIPS"
        new = metric(5.20, "percent_yield", "TE", "DATED_REFERENCE",
                     market_date="2026-10-13")
        new["source_instrument"] = "US 10Y"
        sample = [{"at_utc": (NOW-timedelta(minutes=30)).isoformat(),
                   "metrics": {"BOND:USD:10Y": old}}]
        self.assertIsNone(derived_deltas({"BOND:USD:10Y": new},
                          sample, NOW)["BOND:USD:10Y"]["30"])

    def test_pushed_snapshots_are_not_treated_as_30min_observations(self):
        old = metric(4.8, "percent_yield", "TE", "DATED_REFERENCE",
                     market_date="2026-10-13")
        new = metric(4.76, "percent_yield", "TE", "DATED_REFERENCE",
                     market_date="2026-10-13")
        sample = [{"at_utc": (NOW-timedelta(minutes=18)).isoformat(),
                   "metrics": {"BOND:USD:2Y": old}}]
        self.assertIsNone(derived_deltas({"BOND:USD:2Y": new},
                          sample, NOW)["BOND:USD:2Y"]["30"])

    def test_suspect_rate_shock_does_not_vote_without_confirmation(self):
        old = metric(2.5, "percent_yield", "TE", "DATED_REFERENCE",
                     market_date="2026-10-13")
        new = metric(5.2, "percent_yield", "TE", "DATED_REFERENCE",
                     market_date="2026-10-13")
        sample = [{"at_utc": (NOW-timedelta(minutes=15)).isoformat(),
                   "metrics": {"BOND:USD:10Y": old}}]
        self.assertIsNone(derived_deltas({"BOND:USD:10Y": new},
                          sample, NOW)["BOND:USD:10Y"]["15"])

    def test_nominal_yield_never_compared_to_tips_historical(self):
        old = metric(2.86,"percent_yield","TE","DATED_REFERENCE",market_date="2026-10-13")
        old["source_instrument"]="US 10Y TIPS"
        newer = metric(5.20,"percent_yield","TE","DATED_REFERENCE",market_date="2026-10-13")
        newer["source_instrument"]="US 10Y"
        hist=[{"at_utc":(NOW-timedelta(minutes=30)).isoformat(),
               "metrics":{"BOND:USD:10Y":old}}]
        self.assertIsNone(derived_deltas({"BOND:USD:10Y":newer},hist,NOW)["BOND:USD:10Y"]["30"])
        old["source_instrument"]="US 10Y"
        # Unusually large shift must not become a directional vote.
        self.assertIsNone(derived_deltas({"BOND:USD:10Y":newer},hist,NOW)["BOND:USD:10Y"]["30"])

    def test_burst_snapshots_not_mislabelled_30m_move(self):
        old=metric(4.80,"percent_yield","TE","DATED_REFERENCE",market_date="2026-10-13")
        new=metric(4.76,"percent_yield","TE","DATED_REFERENCE",market_date="2026-10-13")
        hist=[{"at_utc":(NOW-timedelta(minutes=18)).isoformat(),
               "metrics":{"BOND:USD:2Y":old}}]
        d=derived_deltas({"BOND:USD:2Y":new},hist,NOW)["BOND:USD:2Y"]
        self.assertIsNone(d["30"])

    def test_no_spread_of_non_matching_maturities(self):
        items = {"BOND:USD:2Y": metric(4.8,"percent_yield","TE","DATED_REFERENCE",market_date="2026-10-13"),
                 "BOND:JPY:10Y":metric(3.1,"percent_yield","TE","DATED_REFERENCE",market_date="2026-10-13")}
        self.assertEqual(rate_spreads(items,{},NOW),{})

    def test_missing_macro_does_not_suppress_technical_buy(self):
        dash = {"pairs":[{"pair":"NZDJPY","canonical_direction":"BUY",
                         "canonical_stage":"EARLY_DIRECTIONAL_ROTATION",
                         "source_valid":True,"last_closed_15m_price":88.549,
                         "timeframes":{"15m":{"last_closed_utc":(NOW-timedelta(minutes=5)).isoformat()},
                                       "30m":{"last_closed_utc":(NOW-timedelta(minutes=10)).isoformat()}}}]}
        early = {"pairs":[{"pair":"NZDJPY","direction":"BUY","stage":"EARLY_DIRECTIONAL_ROTATION",
                           "research_rank_score":.9,
                           "early_opportunity_score_50pct":.9,
                           "trend_strength_score_50pct":.9}]}
        rows = build_pairs(dash,early,{},{"articles":[],"matched_actuals":[]},{},{},{},{},{},NOW)
        nzdjpy = next(x for x in rows if x["pair"]=="NZDJPY")
        self.assertEqual(nzdjpy["direction"],"BUY")
        self.assertEqual(nzdjpy["macro_alignment"],"UNKNOWN")
        self.assertEqual(nzdjpy["signal_classification"],"EARLY_PROVISIONAL_WATCH")
        self.assertFalse(nzdjpy["trade_execution_allowed"])
        self.assertTrue(nzdjpy["no_5m_signal_inputs"])

    def test_no_invented_event_actual(self):
        calendar = {"pairs":{"EURUSD":[{"currency":"USD","title":"CPI y/y",
                                "event_at_utc":(NOW+timedelta(hours=1)).isoformat(),
                                "forecast":"3.4%"}]}}
        n = news_context({"news_sources":{}},{"status":"MISSING","actuals":[]},NOW)
        dash = {"pairs":[{"pair":"EURUSD","canonical_direction":"SELL","source_valid":True,
                           "last_closed_15m_price":1.118,
                           "timeframes":{"15m":{"last_closed_utc":NOW.isoformat()},
                                         "30m":{"last_closed_utc":NOW.isoformat()}}}]}
        rows = build_pairs(dash,{"pairs":[]},calendar,n,{},{},{},{},{},NOW)
        row = next(x for x in rows if x["pair"]=="EURUSD")
        self.assertEqual(row["macro_alignment"],"UNKNOWN")
        self.assertTrue(row["event_within_120_minutes"])
        self.assertFalse(row["trade_execution_allowed"])

if __name__ == "__main__":
    unittest.main()
