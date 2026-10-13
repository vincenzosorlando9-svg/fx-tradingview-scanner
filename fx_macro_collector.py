#!/usr/bin/env python3
"""Keyless, best-effort public macro references. Never label scraped pages as real-time quotes.

Source contracts: Trading Economics sovereign yields and policy rates, ForexCracked
non-crude/indicative FX, OilPrice.com ONLY for WTI/Brent, FearGreedMeter (NOT CNN),
Reuters + FXStreet headlines, and public Trading Economics global-risk references.
Every observation has its own publisher freshness / effective date.
"""
import concurrent.futures
import csv
import io
import json
import math
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

UTC = timezone.utc
PAIRS = ("AUDUSD", "NZDUSD", "EURUSD", "GBPUSD", "USDJPY",
         "AUDJPY", "NZDJPY", "EURJPY", "EURCAD", "USDCAD", "EURGBP")
COUNTRIES = {
    "USD": "united-states", "EUR": "germany", "GBP": "united-kingdom",
    "JPY": "japan", "CAD": "canada", "AUD": "australia", "NZD": "new-zealand",
    "FR": "france", "IT": "italy",
}
BOND_PREFIX = {
    "USD": "US", "EUR": "Germany", "GBP": "UK", "JPY": "Japan",
    "CAD": "Canada", "AUD": "Australia", "NZD": "NZ",
    "FR": "France", "IT": "Italy",
}
BASE_TE = "https://tradingeconomics.com/"
FOREXCRACKED = "https://www.forexcracked.com/web-forex-tools/live-market-rates/"
OILPRICE = "https://oilprice.com/oil-price-charts/"
FEAR_GREED = "https://feargreedmeter.com/"
RISK_PAGES = {
    "KOSPI": "south-korea/stock-market",
    "NIKKEI": "japan/stock-market",
    "CHINA_EQUITIES": "china/stock-market",
    "DXY": "dxy:cur",
}
NEWS_URLS = {
    "FXStreet_RSS": "https://www.fxstreet.com/rss/news",
    "Reuters_currency_page": "https://www.reuters.com/markets/currencies/",
}
USER_AGENT = "Mozilla/5.0 (compatible; FX-Macro-Research/1.0; public-page-read)"
MAX_BYTES = 1_600_000
MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
MONTH_PATTERN = "(?:" + "|".join(MONTHS) + ")"

def utcnow():
    return datetime.now(UTC)

def stamp(d=None):
    return (d or utcnow()).astimezone(UTC).isoformat()

def numeric(s):
    try:
        x = float(str(s).replace(",", "").replace("%", "").replace("+", "").strip())
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None

def get(url, timeout=12):
    started = utcnow()
    try:
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html, application/xml, application/rss+xml, */*",
        })
        with urllib.request.urlopen(request, timeout=timeout) as response:
            mime = response.headers.get("Content-Type", "")
            data = response.read(MAX_BYTES)
        if not data:
            raise ValueError("empty response")
        return {"url": url, "retrieved_at_utc": stamp(started),
                "http_status": "OK", "mime": mime, "body": data.decode("utf-8", "replace")}
    except Exception as exc:
        return {"url": url, "retrieved_at_utc": stamp(started),
                "http_status": "UNAVAILABLE_" + type(exc).__name__.upper(),
                "error": str(exc)[:180], "body": ""}

def text_of(body):
    soup = BeautifulSoup(body, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return re.sub(r"\s+", " ", unescape(soup.get_text(" ", strip=True)))

def date_from_stats(txt):
    """Only a dated market observation; 'last updated' may be a page update."""
    m = re.search(r"\b(?:on|as of)\s+(" + MONTH_PATTERN +
                  r"\s+\d{1,2},?\s+20\d{2})\b", txt, re.I)
    if m:
        try:
            return datetime.strptime(m.group(1).replace(",", ""), "%B %d %Y").date().isoformat()
        except ValueError:
            return None
    return None

def source_date(text):
    stats = re.search(r"\b(?:Stock Market(?: Index(?: \([^)]*\))?)?|Bond Yield|Note Yield|Interest Rate)\s+-\s+Stats\b",
                      text, re.I)
    if stats:
        d = date_from_stats(text[stats.end():stats.end() + 1100])
        if d:
            return d
    return date_from_stats(text[:2200])

def reference_status(date_s, now=None):
    if not date_s:
        return "UNDATED_REFERENCE"
    now = now or utcnow()
    try:
        days = (now.date() - datetime.fromisoformat(date_s).date()).days
    except ValueError:
        return "UNDATED_REFERENCE"
    if days < -1:
        return "FUTURE_DATED_REJECTED"
    return "DATED_REFERENCE" if days <= 3 else "STALE_DATED_REFERENCE"

def extract_bond_table(html, country):
    """Reads the published Bonds/Yield/Day table, NOT numbers in article prose."""
    soup = BeautifulSoup(html, "html.parser")
    wanted = BOND_PREFIX[country]
    out = {}
    for table in soup.find_all("table"):
        head = " ".join(c.get_text(" ", strip=True) for c in table.find_all("th", limit=12)).lower()
        if not ("yield" in head and ("bond" in head or "bonds" in head)):
            continue
        for row in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"], recursive=False)]
            if len(cells) < 2:
                continue
            label = re.sub(r"\s+", " ", cells[0]).strip()
            label_lower = label.lower()
            if not label_lower.startswith(wanted.lower() + " "):
                continue
            m = re.fullmatch(re.escape(wanted) + r"\s+(2|5|10|30)Y", label, re.I)
            if not m:
                continue
            years = m.group(1) + "Y"
            number = numeric(cells[1])
            if number is None or not -5 <= number <= 30:
                continue
            # Source day changes are yield percentage-point changes, NOT intraday moves.
            day = next((numeric(c) for c in cells[2:] if re.fullmatch(
                r"[+\-]?\d+(?:\.\d+)?\s*%", c.replace(",", ""))), None)
            out[years] = {"value_pct": number, "publisher_day_change_pp": day, "source_row": label}
        if out:
            break
    return out

def parse_bonds(page, country):
    obj = {"source": "Trading Economics", "url": page["url"],
           "retrieved_at_utc": page["retrieved_at_utc"],
           "status": page["http_status"], "market_date": None, "maturities": {},
           "quote_timestamp_utc": None, "live_quote_verified": False}
    if page["http_status"] != "OK":
        return obj
    t = text_of(page["body"])
    if "bond" not in t.lower() and "yield" not in t.lower():
        obj["status"] = "UNRECOGNIZED_PAGE"
        return obj
    obj["market_date"] = source_date(t)
    obj["status"] = reference_status(obj["market_date"])
    obj["maturities"] = extract_bond_table(page["body"], country)
    # Some tenors are not listed for every country: never fill gaps with guesses.
    if not obj["maturities"]:
        obj["status"] = "UNAVAILABLE_NO_VERIFIED_BOND_TABLE"
    if obj["status"] == "FUTURE_DATED_REJECTED":
        obj["maturities"] = {}
    return obj

def parse_policy(page, currency):
    obj = {"source": "Trading Economics policy-rate public page", "url": page["url"],
           "retrieved_at_utc": page["retrieved_at_utc"], "status": page["http_status"],
           "policy_rate_pct": None, "reference_date": None, "reference_period": None,
           "ois_rate_pct": None, "ois_status": "UNAVAILABLE_NO_VALIDATED_PUBLIC_OIS"}
    if page["http_status"] != "OK":
        return obj
    t = text_of(page["body"])
    if "interest rate" not in t.lower():
        obj["status"] = "UNRECOGNIZED_PAGE"
        return obj
    # Policy-rate series are often published MONTHLY. Do not assign today's
    # date to a September rate merely because the HTML was downloaded today.
    m = re.search(r"\b(?:benchmark|key)\s+interest rate\b.{0,130}?"
                  r"(?:last recorded at|was|stands at|remains at)\s+"
                  r"([+\-]?\d{1,2}(?:\.\d{1,4})?)\s+percent", t, re.I)
    if not m:
        m = re.search(r"\binterest rate.{0,90}?\b(?:last recorded at|stands at)\s+"
                      r"([+\-]?\d{1,2}(?:\.\d{1,4})?)\s+percent", t, re.I)
    if m:
        val = numeric(m.group(1))
        if val is not None and -5 <= val <= 30:
            obj["policy_rate_pct"] = val
    # Extract month/year only from an explicit Related rates table, not prose.
    soup = BeautifulSoup(page["body"], "html.parser")
    policy_label = {"USD": "Fed Interest Rate", "EUR": "ECB Interest Rate",
                    "GBP": "BoE Interest Rate", "JPY": "Japan Interest Rate",
                    "CAD": "Canada Interest Rate", "AUD": "Australia Interest Rate",
                    "NZD": "New Zealand Interest Rate"}[currency]
    for tr in soup.select("tr"):
        cells = [x.get_text(" ", strip=True) for x in tr.find_all(["td", "th"], recursive=False)]
        if len(cells) < 5 or cells[0].strip().lower() != policy_label.lower():
            continue
        rate = numeric(cells[1])
        mdate = re.fullmatch(r"[A-Za-z]{3}\s+20\d{2}", cells[-1])
        if rate is None or not mdate or not -5 <= rate <= 30:
            continue
        if obj["policy_rate_pct"] is not None and abs(rate - obj["policy_rate_pct"]) > .015:
            continue
        obj["policy_rate_pct"] = rate
        obj["reference_period"] = cells[-1]
        break
    obj["status"] = "REPORTED_PUBLISHED_POLICY_RATE_NOT_OIS" if obj["policy_rate_pct"] is not None else "UNAVAILABLE_RATE_NOT_FOUND"
    return obj


def parse_index(page, symbol):
    obj = {"source": "Trading Economics public dated market reference", "url": page["url"],
           "retrieved_at_utc": page["retrieved_at_utc"], "status": page["http_status"],
           "value": None, "daily_change_pct": None, "market_date": None,
           "quote_timestamp_utc": None, "verified_intraday": False}
    if page["http_status"] != "OK":
        return obj
    text = text_of(page["body"])
    wanted = {"KOSPI": "KOSPI", "NIKKEI": "JP225",
              "CHINA_EQUITIES": "SHANGHAI", "DXY": "DXY"}[symbol]
    # Use a labelled table row (not arbitrary price or unrelated headline).
    soup = BeautifulSoup(page["body"], "html.parser")
    for table in soup.find_all("table"):
        header = " ".join(th.get_text(" ", strip=True) for th in table.find_all("th")[:10]).lower()
        if ("indexes" not in header and "crosses" not in header) or "price" not in header:
            continue
        for row in table.find_all("tr"):
            cells = [el.get_text(" ", strip=True) for el in row.find_all(["td","th"], recursive=False)]
            if len(cells) < 2:
                continue
            if cells[0].strip().upper() != wanted:
                continue
            price = numeric(cells[1])
            if price is None or not .01 < price < 1e7:
                continue
            obj["value"] = price
            changes = [numeric(x) for x in cells[2:]
                       if re.fullmatch(r"[+\-]?\d+(?:\.\d+)?%", x.replace(",",""))]
            if changes:
                obj["daily_change_pct"] = changes[0]  # first % column is the DAY, not YEAR
            break
        if obj["value"] is not None:
            break
    # Header cards sometimes render when the row table is server-side absent.
    if obj["value"] is None:
        m = re.search(r"\b(?:Actual|Exchange Rate)\s+([\d,]+(?:\.\d+)?)"
                      r"\s+Daily Change\s+([+\-]?\d+(?:\.\d+)?)\s*%", text, re.I)
        if m:
            obj["value"], obj["daily_change_pct"] = numeric(m.group(1)), numeric(m.group(2))
    # For the KOSPI: unambiguous dated stats prose fallback, no later news.
    if obj["value"] is None and symbol == "KOSPI":
        stat = re.search(r"South Korea Stock Market - Stats\s+(.{0,1000})", text, re.I)
        st = stat.group(1) if stat else ""
        m = re.search(r"\bKOSPI,\s+(?:fell|rose|climbed|slipped|plunged)"
                      r"\s+to\s+([\d,]+(?:\.\d+)?)\s+points\s+on\s+"
                      r"(" + MONTH_PATTERN + r"\s+\d{1,2},\s+20\d{2})"
                      r".{0,90}?\b(?:losing|gaining|falling|rising)\s+"
                      r"([\d.]+)\s*%", st, re.I)
        if m:
            obj["value"] = numeric(m.group(1))
            obj["daily_change_pct"] = (-1 if "fell" in m.group(0) or "plunged" in m.group(0) or "slipped" in m.group(0) else 1) * float(m.group(3))
    obj["market_date"] = source_date(text)
    # Currency DXY page does not include a Stock Market - Stats section.
    if not obj["market_date"] and symbol == "DXY":
        today = utcnow().date()
        today_in_text = today.strftime("%B ") + str(today.day)
        if re.search(r"\bDollar Index traded at\b.{0,140}?\bthis\s+\w+\s+" +
                     re.escape(today_in_text) + r"(?:st|nd|rd|th)?\b", text, re.I):
            obj["market_date"] = today.isoformat()
            obj["date_method"] = "PUBLIC_DESCRIPTION_MONTH_DAY_MATCHES_FETCH_UTC_DATE"
    obj["status"] = reference_status(obj["market_date"]) if obj["value"] is not None else "UNAVAILABLE_NO_DATED_INDEX_VALUE"
    if obj["status"] == "FUTURE_DATED_REJECTED":
        obj["value"] = None
    return obj


def parse_cboe_vix(page):
    """Cboe official historical VIX daily close, NOT live VIX nor option flows."""
    obj={"source":"Cboe official VIX historical daily CSV","url":page["url"],
         "retrieved_at_utc":page["retrieved_at_utc"],"status":page["http_status"],
         "value":None,"previous_close":None,"daily_change_pct":None,
         "market_date":None,"verified_intraday":False,"observation_type":"DAILY_CLOSE"}
    if page["http_status"]!="OK":
        return obj
    observations=[]
    try:
        for row in csv.DictReader(io.StringIO(page["body"])):
            fields={str(k).upper().strip():str(v or "").strip() for k,v in row.items()}
            raw_date=fields.get("DATE")
            close=numeric(fields.get("CLOSE"))
            if not raw_date or close is None or not 1<=close<=150:
                continue
            day=None
            for fmt in ("%m/%d/%Y","%Y-%m-%d"):
                try:
                    day=datetime.strptime(raw_date,fmt).date()
                    break
                except ValueError:
                    continue
            if day is None or day>utcnow().date():
                continue
            observations.append((day,close))
    except (csv.Error,TypeError):
        observations=[]
    if not observations:
        obj["status"]="UNAVAILABLE_NO_VALID_DAILY_CSV"
        return obj
    observations=sorted(set(observations))
    last=observations[-1]
    obj["market_date"]=last[0].isoformat()
    obj["value"]=last[1]
    if len(observations)>=2:
        prior=observations[-2][1]
        obj["previous_close"]=prior
        obj["daily_change_pct"]=round(100*(last[1]-prior)/prior,3)
    obj["status"]=reference_status(obj["market_date"])
    return obj

def parse_te_noncrude(page):
    """Dated Trading Economics commodity TABLE fallback, never OilPrice crude."""
    data={"source":"Trading Economics public commodities table (secondary to ForexCracked)",
          "url":page["url"],"retrieved_at_utc":page["retrieved_at_utc"],
          "status":page["http_status"],"commodities":{},
          "verified_intraday_quote":False}
    if page["http_status"]!="OK":
        return data
    soup=BeautifulSoup(page["body"],"html.parser")
    supported={
        "GOLD":(r"Gold\s+USD/t\.oz","USD_per_troy_oz"),
        "SILVER":(r"Silver\s+USD/t\.oz","USD_per_troy_oz"),
        "COPPER":(r"Copper\s+USD/Lbs","USD_per_lb"),
        "IRON_ORE":(r"Iron Ore\s+USD/T","USD_per_tonne"),
        "COAL":(r"Coal\s+USD/T","USD_per_tonne"),
        "EU_GAS":(r"EU Gas\s+EUR/MWh","EUR_per_MWh"),
        "NATURAL_GAS":(r"Natural gas\s+USD/MMBtu","USD_per_MMBtu"),
    }
    date_now=utcnow().date()
    for table in soup.find_all("table"):
        head=" ".join(x.get_text(" ",strip=True) for x in table.find_all("th")[:12]).lower()
        if "price" not in head or ("date" not in head and "monthly" not in head):
            continue
        for tr in table.find_all("tr"):
            cells=[x.get_text(" ",strip=True) for x in tr.find_all(["td","th"],recursive=False)]
            if len(cells)<4:
                continue
            label=cells[0].strip()
            candidate=next(((k,unit) for k,(pattern,unit) in supported.items()
                            if re.fullmatch(pattern,label,re.I)),None)
            if not candidate:
                continue
            key,unit=candidate
            v=numeric(cells[1])
            if v is None or v<=0 or v>1_000_000:
                continue
            daychg=next((numeric(c) for c in cells[2:5] if re.fullmatch(
                r"[+\-]?\d+(?:\.\d+)?\s*%",c.replace(",",""))),None)
            dated=next((c for c in reversed(cells) if re.fullmatch(
                r"[A-Za-z]{3}/\d{1,2}",c.strip())),None)
            date_iso=None
            if dated:
                try:
                    d=datetime.strptime(dated+"/"+str(date_now.year),"%b/%d/%Y").date()
                    if d > date_now+timedelta(days=1):
                        d=d.replace(year=d.year-1)
                    date_iso=d.isoformat()
                except ValueError:
                    pass
            status=reference_status(date_iso)
            if status in ("UNDATED_REFERENCE","FUTURE_DATED_REJECTED"):
                continue
            data["commodities"][key]={
                "value":v, "unit":unit,"daily_change_pct":daychg,
                "market_date":date_iso,"status":status,
                "verified_intraday_quote":False,
                "source":"Trading Economics public commodity table",
                "source_url":page["url"],
                "retrieved_at_utc":page["retrieved_at_utc"]}
    data["status"]="DATED_PUBLIC_COMMODITY_REFERENCES" if data["commodities"] else "UNAVAILABLE_NO_RECOGNIZED_COMMODITY_ROWS"
    return data

def parse_forexcracked(page):
    result = {"source": "ForexCracked live-market-rates public page",
              "url": page["url"], "retrieved_at_utc": page["retrieved_at_utc"],
              "status": page["http_status"], "pairs": {}, "non_crude": {},
              "cross_risk": {},
              "quote_timestamp_utc": None, "indicative_not_broker_executable": True}
    if page["http_status"] != "OK":
        return result
    txt = text_of(page["body"])
    lag = re.search(r"\bLast update:\s*(\d+)\s*(seconds?|minutes?)\s+ago\b", txt, re.I)
    if lag:
        elapsed = int(lag.group(1)) * (60 if "minute" in lag.group(2).lower() else 1)
        if 0 <= elapsed <= 1200:
            retrieved = datetime.fromisoformat(page["retrieved_at_utc"])
            result["quote_timestamp_utc"] = stamp(retrieved - timedelta(seconds=elapsed))
            result["publisher_time_method"] = "APPROXIMATE_EXPLICIT_RELATIVE_SITE_CLOCK"
    for pair in PAIRS:
        label = pair[:3] + "/" + pair[3:]
        pat = r"(?<![A-Z])" + re.escape(label) + \
              r"\s+(?:(\d+(?:\.\d+)?)p\s+)?([0-9]{1,4}\.[0-9]{2,6})\s+[▲▼]?\s*Ask\s+([0-9]{1,4}\.[0-9]{2,6})"
        match = re.search(pat, txt, re.I)
        if not match:
            continue
        bid, ask = numeric(match.group(2)), numeric(match.group(3))
        if bid is None or ask is None or bid <= 0 or ask < bid:
            continue
        pip = .01 if pair.endswith("JPY") else .0001
        spread = round((ask - bid) / pip, 2)
        if not 0 <= spread <= 100:
            continue
        result["pairs"][pair] = {"bid": bid, "ask": ask, "spread_pips": spread,
                                "publisher_spread_pips": numeric(match.group(1)),
                                "quote_timestamp_utc": result["quote_timestamp_utc"],
                                "status": "INDICATIVE_SITE_QUOTE_NOT_BROKER",
                                "execution_allowed": False}
    # Supplemental non-crude market context from the actual website symbol
    # labels. Require a *bid followed by explicit Ask*, not arbitrary figures
    # in articles/news/promotions. Never use XBR/USD or other ForexCracked
    # crude references: the user mandates OilPrice.com ONLY for WTI/Brent.
    def labelled_bid_ask(label):
        pat=(r"(?<![A-Z0-9/])" + re.escape(label) +
             r"\s+(?:(?:[\d,]+(?:\.\d+)?p?)\s+)?"
             r"([\d,]+(?:\.\d+)?)\s*[▲▼]?\s*Ask\s+"
             r"([\d,]+(?:\.\d+)?)")
        m=re.search(pat,txt,re.I)
        if not m:
            return None
        bid,ask=numeric(m.group(1)),numeric(m.group(2))
        if bid is None or ask is None or bid<=0 or ask<bid:
            return None
        return bid,ask
    others=(("XAU/USD","GOLD"),("XAG/USD","SILVER"),
            ("XCU/USD","COPPER"),("XNG/USD","NATURAL_GAS"),
            ("ALUMINIUM","ALUMINIUM"),("NICKEL","NICKEL"),
            ("SOYBEANS","SOYBEANS"),("WHEAT","WHEAT"),
            ("CORN","CORN"),("COCOA","COCOA"),
            ("COFFEE","COFFEE"))
    for label,key in others:
        vals=labelled_bid_ask(label)
        if not vals:
            continue
        bid,ask=vals
        bounds={"GOLD":(200,10000),"SILVER":(3,500),
                "COPPER":(.4,30),"NATURAL_GAS":(.1,50),
                "ALUMINIUM":(300,15000),"NICKEL":(3000,100000)}
        limits=bounds.get(key,(.01,1000000))
        if not limits[0]<=bid<=limits[1]:
            continue
        result["non_crude"][key]={
            "value":bid,"bid":bid,"ask":ask,
            "status":"INDICATIVE_PUBLIC_SITE_REFERENCE_NOT_BROKER",
            "unit":"SOURCE_QUOTE_UNITS",
            "instrument_label":label,
            "quote_timestamp_utc":result["quote_timestamp_utc"],
            "execution_allowed":False}
    vals=labelled_bid_ask("USD/CNH")
    if vals and 3<=vals[0]<=12:
        result["cross_risk"]["USD_CNH"]={
            "bid":vals[0], "ask":vals[1],
            "status":"INDICATIVE_CHINA_CONTEXT_NOT_ONE_OF_11_SIGNAL_PAIRS",
            "quote_timestamp_utc":result["quote_timestamp_utc"],
            "execution_allowed":False}
    # IRON_ORE and DAIRY are only present if a validated source row exists;
    # never infer their prices from adjacent or unrelated text.
    result["status"] = "INDICATIVE_PUBLIC_QUOTES" if result["pairs"] or result["non_crude"] else "UNAVAILABLE_NO_STATIC_QUOTES"
    return result

def parse_oilprice(page):
    result = {"source": "OilPrice.com ONLY", "url": page["url"],
              "retrieved_at_utc": page["retrieved_at_utc"], "status": page["http_status"],
              "commodities": {}, "verified_live_quote": False}
    if page["http_status"] != "OK":
        return result
    soup = BeautifulSoup(page["body"], "html.parser")
    for row in soup.select("tr"):
        parts = [c.get_text(" ", strip=True) for c in row.find_all(["th", "td"], recursive=False)]
        if not parts:
            continue
        text = " ".join(parts)
        key = "WTI" if re.search(r"\bWTI Crude\b", text, re.I) else "BRENT" if re.search(r"\bBrent Crude\b", text, re.I) else None
        if not key:
            continue
        price = next((numeric(x) for x in parts[1:] if re.fullmatch(r"\$?\d{1,4}\.\d{1,4}", x)), None)
        if price is None or not 5 <= price <= 500:
            continue
        delay = re.search(r"(\d{1,3})[- ]Minute Delay", text, re.I)
        result["commodities"][key] = {
            "value_usd_per_barrel": price, "delay_minutes": int(delay.group(1)) if delay else None,
            "status": "DELAYED_SOURCE_REFERENCE" if delay else "PUBLISHER_TIME_UNVERIFIED",
            "quote_timestamp_utc": None, "source": "OilPrice.com"}
    result["status"] = "DELAYED_OR_UNTIMED_PUBLIC_REFERENCE" if result["commodities"] else "UNAVAILABLE_NO_RECOGNIZED_OIL_ROWS"
    return result

def parse_feargreed(page):
    result = {"source": "FearGreedMeter (CNN EXCLUDED)", "url": page["url"],
              "retrieved_at_utc": page["retrieved_at_utc"],
              "status": page["http_status"], "index": None, "label": None,
              "publisher_lag_minutes": None, "quote_timestamp_utc": None,
              "vix": None}
    if page["http_status"] != "OK":
        return result
    soup = BeautifulSoup(page["body"], "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    m = re.search(r"Fear and Greed Index\s*:\s*(\d{1,3})\s*\(([^)]+)\)", title, re.I)
    if m:
        v = int(m.group(1))
        if 0 <= v <= 100:
            result["index"] = v
            result["label"] = m.group(2).strip().upper()
    txt = text_of(page["body"])
    m = re.search(r"\b(\d{1,3})\s+(minutes?|hours?)\s+ago\b", txt, re.I)
    if m:
        lag = int(m.group(1)) * (60 if "hour" in m.group(2).lower() else 1)
        result["publisher_lag_minutes"] = lag
        if lag <= 240:
            result["quote_timestamp_utc"] = stamp(datetime.fromisoformat(page["retrieved_at_utc"]) - timedelta(minutes=lag))
    vix = re.search(r"\bVIX\s+(?:Normal|Low|High|Elevated|Extreme)?\s*(\d{1,3}(?:\.\d+)?)\b", txt, re.I)
    if vix:
        result["vix"] = numeric(vix.group(1))
    result["status"] = "PUBLIC_INDEX_RELATIVE_TIME" if result["index"] is not None and result["quote_timestamp_utc"] else (
        "UNTIMED_REFERENCE" if result["index"] is not None else "UNAVAILABLE_INDEX_NOT_FOUND")
    return result

def news_currency_tags(title):
    # Explicit article terms only; don't infer positive/negative currency moves from prose.
    terms = {"USD": ("us dollar", "u.s. dollar", "greenback", "dxy", "fed", "fomc", "treasury", "u.s. yields", "us yields"),
             "EUR": ("euro", "ecb", "eurozone", "bund"),
             "GBP": ("sterling", "pound", "boe", "bank of england"),
             "JPY": ("yen", "boj", "bank of japan", "japan"),
             "CAD": ("canadian dollar", "bank of canada", "loonie", "crude oil", "oil prices"),
             "AUD": ("australian dollar", "aussie", "rba", "australia"),
             "NZD": ("new zealand dollar", "kiwi", "rbnz", "new zealand"),
             "CNY": ("china", "yuan", "renminbi", "beijing")}
    value = title.lower()
    return [c for c, words in terms.items() if any(w in value for w in words)]

def parse_news(page, provider):
    item = {"source": provider, "url": page["url"], "retrieved_at_utc": page["retrieved_at_utc"],
            "status": page["http_status"], "articles": []}
    if page["http_status"] != "OK":
        return item
    html = page["body"]
    found = []
    if "<rss" in html[:1000].lower() or "<feed" in html[:1000].lower():
        try:
            root = ET.fromstring(html)
            for row in list(root.findall(".//item")) + list(root.findall(".//{http://www.w3.org/2005/Atom}entry")):
                title = row.findtext("title") or row.findtext("{http://www.w3.org/2005/Atom}title")
                url = row.findtext("link")
                if not url:
                    atom = row.find("{http://www.w3.org/2005/Atom}link")
                    url = atom.get("href") if atom is not None else None
                raw_date = (row.findtext("pubDate") or row.findtext("{http://www.w3.org/2005/Atom}updated") or
                            row.findtext("{http://www.w3.org/2005/Atom}published"))
                when = None
                try:
                    if raw_date:
                        when = parsedate_to_datetime(raw_date) if "," in raw_date else datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                        if when.tzinfo is None:
                            when = None
                except (ValueError, TypeError):
                    pass
                if title and url and when:
                    found.append((title.strip(), url.strip(), stamp(when)))
        except ET.ParseError:
            item["parse_note"] = "INVALID_RSS_XML"
    else:
        soup = BeautifulSoup(html, "html.parser")
        for block in soup.select("article, [data-testid='MediaStoryCard'], [class*='story-card']")[:60]:
            a = block.find("a", href=True)
            t = block.find("time", datetime=True)
            if not a or not t:
                continue
            title = a.get_text(" ", strip=True)
            raw_date = t.get("datetime")
            try:
                when = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                if when.tzinfo is None:
                    continue
            except (ValueError, TypeError, AttributeError):
                continue
            url = a["href"]
            if url.startswith("/"):
                from urllib.parse import urlparse
                origin = urlparse(page["url"])
                url = origin.scheme + "://" + origin.netloc + url
            if title and url.startswith("https://"):
                found.append((title, url, stamp(when)))
    now = utcnow()
    seen = set()
    for title, url, published in found:
        when = datetime.fromisoformat(published)
        if when < now - timedelta(hours=48) or when > now + timedelta(minutes=5):
            continue
        if url in seen:
            continue
        seen.add(url)
        item["articles"].append({"title": title[:220], "url": url,
                                 "published_at_utc": published,
                                 "currencies": news_currency_tags(title),
                                 "direction": "UNDETERMINED_FROM_HEADLINE_ONLY"})
    item["articles"].sort(key=lambda x: x["published_at_utc"], reverse=True)
    item["articles"] = item["articles"][:35]
    item["status"] = "DATED_HEADLINES" if item["articles"] else "NO_VERIFIABLE_DATED_HEADLINES"
    return item

def collect():
    tasks = {}
    for c, slug in COUNTRIES.items():
        tasks["yield:" + c] = BASE_TE + slug + "/government-bond-yield"
        if c in ("USD", "EUR", "GBP", "JPY", "CAD", "AUD", "NZD"):
            tasks["policy:" + c] = BASE_TE + ("euro-area" if c == "EUR" else slug) + "/interest-rate"
    tasks.update({"risk:" + k: BASE_TE + v for k, v in RISK_PAGES.items()})
    tasks.update({"vix_cboe":"https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv",
                  "te_noncrude": BASE_TE+"commodities",
                  "forexcracked": FOREXCRACKED, "oilprice": OILPRICE,
                  "feargreed": FEAR_GREED})
    tasks.update({"news:" + k: v for k, v in NEWS_URLS.items()})
    pages = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        futures = {pool.submit(get, url): key for key, url in tasks.items()}
        for future in concurrent.futures.as_completed(futures):
            pages[futures[future]] = future.result()
    bonds = {c: parse_bonds(pages["yield:" + c], c) for c in COUNTRIES}
    policies = {c: parse_policy(pages["policy:" + c], c)
                for c in ("USD", "EUR", "GBP", "JPY", "CAD", "AUD", "NZD")}
    risk = {k: parse_index(pages["risk:" + k], k) for k in RISK_PAGES}
    news = {k: parse_news(pages["news:" + k], k) for k in NEWS_URLS}
    out = {"schema_version": 1, "collected_at_utc": stamp(),
           "scope": "PUBLIC_KEYLESS_MARKET_REFERENCES_NOT_BROKER_LIVE",
           "configured_countries": list(COUNTRIES), "covered_fx_pairs": list(PAIRS),
           "bonds": bonds, "policy_rates": policies, "indices": risk,
           "vix_cboe_official_daily": parse_cboe_vix(pages["vix_cboe"]),
           "noncrude_te_secondary": parse_te_noncrude(pages["te_noncrude"]),
           "forexcracked": parse_forexcracked(pages["forexcracked"]),
           "oilprice": parse_oilprice(pages["oilprice"]),
           "feargreedmeter": parse_feargreed(pages["feargreed"]),
           "news_sources": news,
           "ois": {"status": "UNAVAILABLE_NO_VERIFIED_PUBLIC_OIS", "actual_rate": None},
           "cme_futures": {"status": "UNAVAILABLE_NO_VERIFIED_PUBLIC_CONTRACT_DATA"},
           "cftc_tff": {"status": "UNAVAILABLE_NO_VALIDATED_WEEKLY_TFF"},
           "notes": [
               "Yields are Trading Economics public dated references; source refresh does not prove intraday quote refresh.",
               "ForexCracked bid/ask is indicative site information, NOT a broker executable quote.",
               "OilPrice.com may show delay and must never be described as real time.",
               "No CNN, no options layer, no API keys, no automatic orders or alerts.",
           ]}
    return out

def main():
    result = collect()
    Path("fx_macro_raw.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"collected_at_utc": result["collected_at_utc"],
                      "yield_tenors": {c: len(v["maturities"]) for c, v in result["bonds"].items()},
                      "indicative_fx_pairs": len(result["forexcracked"]["pairs"]),
                      "cross_risk": list(result["forexcracked"].get("cross_risk",{})),
                      "crude": list(result["oilprice"]["commodities"]),
                      "news": {k: len(v["articles"]) for k, v in result["news_sources"].items()},
                      "fg_status": result["feargreedmeter"]["status"]}))

if __name__ == "__main__":
    main()
