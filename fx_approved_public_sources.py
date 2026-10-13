#!/usr/bin/env python3
"""Approved PUBLIC FX Blue calendar + DELAYED Newsquawk headlines.

HTML endpoints only; fail closed when date/UTC/publisher clocks cannot be
verified. No paywall circumvention, account, keys, orders, or notifications.
"""
import concurrent.futures
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from fx_macro_collector import get, news_currency_tags

UTC=timezone.utc
FX_BLUE="https://www.fxblue.com/calendar"
NEWSQUAWK="https://www.newsquawk.com/headlines"
NEWSQUAWK_DELAY_MIN=20
CCYS={"USD","EUR","GBP","AUD","JPY","NZD","CAD","CNY"}
NAMES={"US":"USD","USA":"USD","UNITED STATES":"USD",
       "AUSTRALIA":"AUD","JAPAN":"JPY","UK":"GBP","UNITED KINGDOM":"GBP",
       "EUROPEAN UNION":"EUR","EUROZONE":"EUR","GERMANY":"EUR",
       "CANADA":"CAD","NEW ZEALAND":"NZD","CHINA":"CNY"}
DATE_RX=re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),?\s+(\d{1,2})\s+([A-Za-z]{3}),?\s+(\d{1,2}):(\d{2})\b",re.I)
PUBLICATION_RX=re.compile(r"\bPublished\s+(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}),?\s+(\d{1,2}:\d{2})\s+UTC\b",re.I)
RELEVANT_RX=re.compile(r"\b(?:boj|bank of japan|fed|fomc|federal reserve|rba|ecb|boe|rbnz|central bank|rate|yield|inflation|cpi|ppi|jobs|employment|yen|dollar|aussie|sterling|euro|oil|crude|china|geopolitical|treasury|risk off)\b",re.I)


def parse_calendar_utc(value, retrieved):
    m=DATE_RX.search(value or "")
    if not m:
        return None
    day,month,hour,minute=m.groups()
    now=datetime.fromisoformat(retrieved.replace("Z","+00:00"))
    candidates=[]
    for year in [now.year-1,now.year,now.year+1]:
        try:
            d=datetime.strptime(f"{year} {month} {day} {hour}:{minute}","%Y %b %d %H:%M").replace(tzinfo=UTC)
            candidates.append(d)
        except ValueError:
            pass
    if not candidates:
        return None
    best=min(candidates,key=lambda v:abs((v-now).total_seconds()))
    if abs((best-now).total_seconds())>10*24*3600:
        return None  # Key events must be within surrounding week, never force year.
    return best.isoformat()


def parse_fx_blue(page):
    result={"source":"FX Blue public economic calendar","url":FX_BLUE,
            "collected_at_utc":page.get("retrieved_at_utc"),
            "source_status":page.get("http_status"),
            "source_timezone":"UTC_EXPLICIT_PUBLISHER",
            "event_year_resolution":"NEAREST_WITHIN_10_DAYS_OF_COLLECTION",
            "events":[],"status":"UNAVAILABLE",
            "no_api_keys":True,"verified_all_provider_events":False}
    if page.get("http_status")!="OK":
        result["status"]="UNAVAILABLE_FETCH_"+str(page.get("http_status"))
        return result
    soup=BeautifulSoup(page.get("body") or "","html.parser")
    target=next((h for h in soup.find_all(["h1","h2","h3","h4","h5"])
                 if "key events" in h.get_text(" ",strip=True).lower()
                 and "7 days" in h.get_text(" ",strip=True).lower()),None)
    if not target:
        result["status"]="UNAVAILABLE_NO_DATED_KEY_EVENTS_SECTION"
        return result
    table=target.find_next("table")
    if not table:
        result["status"]="UNAVAILABLE_NO_PUBLIC_CALENDAR_TABLE"
        return result
    seen=set()
    for row in table.select("tr"):
        cells=[c.get_text(" ",strip=True) for c in row.find_all(["td","th"],recursive=False)]
        if len(cells)<3:
            continue
        when=parse_calendar_utc(cells[0],result["collected_at_utc"])
        c_raw=cells[1].strip().upper()
        ccy=c_raw if c_raw in CCYS else NAMES.get(c_raw)
        if not when or ccy not in CCYS:
            continue
        title=cells[2].strip()
        impact=cells[3].strip().title() if len(cells)>3 else "Unknown"
        if not title or len(title)<3 or len(title)>210:
            continue
        key=(when,ccy,title.lower())
        if key in seen:continue
        seen.add(key)
        result["events"].append({
            "event_at_utc":when,"currency":ccy,"title":title,
            "impact":impact if impact in ("High","Medium","Low","Holiday") else "Unknown",
            "source_name":"FX Blue public calendar","source_url":FX_BLUE,
            "time_basis":"PUBLISHER_EXPLICIT_UTC_INFERRED_NEAREST_YEAR",
            "publisher_time_verified_from_public_row":True,
            "actual":None,"actual_status":"NOT_VERIFIED",
            "forecast":None,"previous":None})
    result["events"].sort(key=lambda e:e["event_at_utc"])
    result["status"]="DATED_UTC_PUBLIC_EVENTS" if result["events"] else "UNAVAILABLE_NO_PARSEABLE_DATED_EVENTS"
    return result


def parse_newsquawk_article(page):
    if page.get("http_status")!="OK":
        return None
    soup=BeautifulSoup(page.get("body") or "","html.parser")
    h=soup.find("h1")
    title=h.get_text(" ",strip=True) if h else ""
    if not title or len(title)>500:
        return None
    text=soup.get_text(" ",strip=True)
    date=PUBLICATION_RX.search(text[:2400])
    if not date:
        return None
    try:
        published=datetime.strptime(date.group(1)+" "+date.group(2),"%d %b %Y %H:%M").replace(tzinfo=UTC)
    except ValueError:
        try:
            published=datetime.strptime(date.group(1)+" "+date.group(2),"%d %B %Y %H:%M").replace(tzinfo=UTC)
        except ValueError:
            return None
    # Newsquawk homepage is delayed. "On feed at ..." does NOT mean public.
    public_at=published.isoformat()
    url=page.get("url") or ""
    if not url.startswith("https://www.newsquawk.com/headlines/"):
        return None
    return {"title":title[:220],"url":url,"published_at_utc":public_at,
            "currencies":news_currency_tags(title),
            "direction":"UNDETERMINED_FROM_HEADLINE_ONLY",
            "timestamp_basis":"PUBLIC_ARTICLE_PUBLICATION_UTC_NOT_PRO_FEED",
            "public_delay_at_least_minutes":NEWSQUAWK_DELAY_MIN,
            "requires_price_reaction_confirmation":True}


def parse_newsquawk_index(page,limit=9):
    if page.get("http_status")!="OK":
        return []
    soup=BeautifulSoup(page.get("body") or "","html.parser")
    seen=set()
    candidates=[]
    # Restrict to actual public article links; never crawl paid/private service.
    for a in soup.select("a[href]"):
        url=urljoin(NEWSQUAWK,a.get("href") or "")
        parsed=urlparse(url)
        if parsed.netloc!="www.newsquawk.com" or not parsed.path.startswith("/headlines/"):
            continue
        if url in seen:
            continue
        seen.add(url)
        title=a.get_text(" ",strip=True)
        if len(title)<12:continue
        if not RELEVANT_RX.search(title):continue
        candidates.append(url)
        if len(candidates)>=limit:
            break
    return candidates


def collect_newsquawk(page,fetcher=get):
    doc={"source":"Newsquawk public DELAYED headlines",
         "url":NEWSQUAWK,
         "retrieved_at_utc":page.get("retrieved_at_utc"),
         "status":"UNAVAILABLE",
         "public_delay_minutes_at_least":NEWSQUAWK_DELAY_MIN,
         "live_pro_feed_access":False,"paywall_not_accessed":True,"articles":[]}
    if page.get("http_status")!="OK":
        doc["status"]="UNAVAILABLE_FETCH_"+str(page.get("http_status"))
        return doc
    urls=parse_newsquawk_index(page)
    if not urls:
        doc["status"]="UNAVAILABLE_NO_PUBLIC_RELEVANT_ARTICLE_LINKS"
        return doc
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures={url:pool.submit(fetcher,url,7) for url in urls}
        items=[parse_newsquawk_article(f.result()) for f in futures.values()]
    seen=set()
    for item in items:
        if item and item["currencies"] and item["url"] not in seen:
            seen.add(item["url"])
            doc["articles"].append(item)
    doc["articles"].sort(key=lambda a:a["published_at_utc"],reverse=True)
    doc["status"]="DATED_HEADLINES" if doc["articles"] else "UNAVAILABLE_NO_PUBLIC_DATED_CURRENCY_ARTICLES"
    return doc
