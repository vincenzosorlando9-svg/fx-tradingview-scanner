"""KOSPI Asian risk *context* from Trading Economics' public stock-market page.

NO API KEY, no private endpoints. Uses the user-approved public page:
https://tradingeconomics.com/south-korea/stock-market

The page's prominent 'Actual' / 'Daily Change' is a DAILY CFD/reference,
NOT verified intraday KRX exchange quotes. Article copy can describe current
selling while the prominent numeric quote still refers to a prior close.
Never use the news headline as a tick; never invent a publication clock time.
"""
import json
import re
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

URL = "https://tradingeconomics.com/south-korea/stock-market"
OUT = Path("fx_asian_risk.json")
KST = ZoneInfo("Asia/Seoul")
UTC = timezone.utc
MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
MONTH = "(?:" + "|".join(MONTHS) + ")"
MAX_REFERENCE_DAYS = 3


class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style", "noscript", "template"):
            self._skip += 1
        if tag.lower() in ("p", "div", "td", "tr", "h1", "h2", "h3",
                           "li", "section", "br"):
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style", "noscript", "template"):
            self._skip = max(0, self._skip - 1)
        if tag.lower() in ("p", "div", "td", "tr", "h1", "h2", "h3",
                           "li", "section"):
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self._parts.append(data)

    def text(self):
        return re.sub(r"[ \t]+", " ", unescape("".join(self._parts)))


def parse_page(page, now=None):
    """Best-effort static HTML parser; deliberately fails closed if uncertain."""
    now = now or datetime.now(UTC)
    p = VisibleText()
    p.feed(page)
    raw = p.text()
    text = re.sub(r"\s+", " ", raw)
    output = {
        "status": "UNAVAILABLE",
        "provider": "Trading Economics",
        "source_url": URL,
        "instrument": "KOSPI",
        "source_instrument_kind": "PUBLIC_OTC_CFD_DAILY_REFERENCE_NOT_OFFICIAL_KRX",
        "collected_at_utc": now.astimezone(UTC).isoformat(),
        "source_quote_timestamp_utc": None,
        "verified_intraday_quote": False,
        "reference_date_kst": None,
        "reference_age_calendar_days": None,
        "daily_reference_level": None,
        "daily_reference_change_pct": None,
        "daily_reference_status": "UNAVAILABLE",
        "risk_tier_from_daily_reference": "UNAVAILABLE",
        "intraday_news_summary": None,
        "intraday_news_date": None,
        "intraday_news_status": "UNAVAILABLE",
        "news_is_quote": False,
        "safe_interpretation": "KOSPI may corroborate Asia risk sentiment, not cause a particular FX trade.",
        "limitations": [
            "Trading Economics webpage values may be delayed, prior-close or OTC/CFD rather than official KRX.",
            "No independently verified intraday KOSPI quote or tick clock.",
            "Article/news dates are not precise publication times; do not use them to time intraday reversals.",
            "Even a severe daily decline never overrides 15m/30m FX price action."
        ]
    }
    if not ("South Korea Stock Market" in text and "KOSPI" in text):
        output["error"] = "PAGE_NOT_RECOGNIZED"
        return output

    # First 'Actual' and 'Daily Change' values are daily references,
    # intentionally NOT the later headline's 'plunged over 6%' claim.
    head = text[:min(len(text), 4500)]
    price = re.search(r"\bActual\s+([0-9][0-9,]*\.?[0-9]*)\s+(?:Daily Change|Day Change)\b",
                      head, re.IGNORECASE)
    change = re.search(r"\bDaily Change\s+([+-]?[0-9]+(?:\.[0-9]+)?)\s*%", head,
                       re.IGNORECASE)
    if price and change:
        level = float(price.group(1).replace(",", ""))
        daily_change = float(change.group(1))
        if 100 <= level <= 100000 and -30 <= daily_change <= 30:
            output["daily_reference_level"] = level
            output["daily_reference_change_pct"] = daily_change

    # Some TE renders omit the numeric 'Actual' card in server HTML, even
    # while the dated KOSPI Stats sentence provides the same daily CFD close.
    # Parse the stats fallback ONLY if it explicitly includes the points,
    # source date and signed percentage; never use the newer News Stream.
    # The 'Stats' prose is the date of this daily value; do not infer it
    # from news title date, HTTP fetch time, or 'last updated' site clock.
    stat = re.search(r"South Korea Stock Market - Stats\s+(.{0,950})", text,
                     re.IGNORECASE)
    stat_text = stat.group(1) if stat else ""
    quoted = re.search(r"\b(on|as of)\s+(" + MONTH + r"\s+\d{1,2},\s+\d{4})\b",
                       stat_text, re.IGNORECASE)
    if quoted:
        try:
            stamp = datetime.strptime(quoted.group(2), "%B %d, %Y").date()
            output["reference_date_kst"] = stamp.isoformat()
            output["reference_age_calendar_days"] = (now.astimezone(KST).date() - stamp).days
        except ValueError:
            pass

    dated_stats = re.search(
        r"\b(fell|slipped|declined|dropped|plunged|rose|gained|climbed|advanced|rallied)"
        r"\s+to\s+([0-9][0-9,]*\.?[0-9]*)\s+points\s+on\s+("
        + MONTH +
        r"\s+\d{1,2},\s+\d{4})\s*,\s*(losing|falling|gaining|rising)\s+"
        r"([0-9]+(?:\.[0-9]+)?)\s*%", stat_text, re.IGNORECASE)
    if dated_stats and output["reference_date_kst"]:
        verb=dated_stats.group(1).lower()
        qualifier=dated_stats.group(4).lower()
        falling=verb in ("fell","slipped","declined","dropped","plunged")
        consistent=(qualifier in ("losing","falling"))==falling
        value=float(dated_stats.group(2).replace(",",""))
        pct=float(dated_stats.group(5))*(-1 if falling else 1)
        if consistent and 100<=value<=100000 and -30<=pct<=30:
            header_value=output["daily_reference_level"]
            header_pct=output["daily_reference_change_pct"]
            if (header_value is None or
                (abs(header_value-value)/max(1.,value)<.005 and
                 header_pct is not None and abs(header_pct-pct)<.15)):
                output["daily_reference_level"]=value
                output["daily_reference_change_pct"]=pct
            else:
                output["daily_reference_level"]=None
                output["daily_reference_change_pct"]=None
                output["error"]="CONFLICTING_DAILY_SOURCE_VALUES"

    if output["daily_reference_level"] is not None and output["reference_date_kst"]:
        delay = output["reference_age_calendar_days"]
        if -1 <= delay <= MAX_REFERENCE_DAYS:
            output["daily_reference_status"] = "DATED_PUBLIC_DAILY_CFD_REFERENCE"
            daily = output["daily_reference_change_pct"]
            output["risk_tier_from_daily_reference"] = (
                "SEVERE_DAILY_RISK_OFF" if daily <= -3 else
                "ELEVATED_DAILY_RISK_OFF" if daily <= -1.5 else
                "POSITIVE_DAILY_BACKGROUND" if daily >= 1.5 else "NEUTRAL_DAILY_BACKGROUND")
        else:
            output["daily_reference_status"] = "STALE_OR_FUTURE_DATED"
            output["risk_tier_from_daily_reference"] = "UNAVAILABLE"
    else:
        output["daily_reference_status"] = "UNVERIFIED_DAILY_REFERENCE"

    section = re.search(r"\bNews Stream\s+(.{0,3500})", text, re.IGNORECASE)
    if section:
        news = section.group(1)
        # Prefer first South Korean KOSPI headline; date if visible only.
        m = re.search(r"(South Korean Shares.{0,105})", news, re.IGNORECASE)
        if m:
            headline = m.group(1)
            # Keep the headline only up to common first-sentence delimiting.
            headline = re.split(r"(?:(?:The benchmark|The KOSPI|The Korean|South Korea's)\s)", headline)[0].strip()
            output["intraday_news_summary"] = headline[:140]
            d = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", news[:1600])
            if d:
                output["intraday_news_date"] = d.group(1)
            output["intraday_news_status"] = "DATED_NEWS_CONTEXT_ONLY_NO_QUOTE_TIME"
    output["status"] = (
        "PARTIAL_DAILY_REFERENCE" if output["daily_reference_status"] ==
        "DATED_PUBLIC_DAILY_CFD_REFERENCE" else
        "PARTIAL_NEWS_ONLY" if output["intraday_news_summary"] else
        "UNAVAILABLE")
    return output


def retrieve(url=URL, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; FXRiskResearch/1.0)",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        ctype = response.headers.get("Content-Type", "")
        if "html" not in ctype.lower():
            raise ValueError("SOURCE_NOT_HTML")
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError("PAGE_TOO_LARGE")
    return body.decode("utf-8", errors="replace")


def main():
    now = datetime.now(UTC)
    try:
        result = parse_page(retrieve(), now)
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as exc:
        result = parse_page("", now)
        result["error"] = type(exc).__name__
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print("KOSPI no-key public page:", result["status"],
          "daily change:", result["daily_reference_change_pct"],
          "reference date:", result["reference_date_kst"],
          "intraday quote verified:", result["verified_intraday_quote"],
          "error:", result.get("error"))


if __name__ == "__main__":
    main()
