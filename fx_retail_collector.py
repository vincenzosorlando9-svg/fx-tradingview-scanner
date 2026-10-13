#!/usr/bin/env python3
"""Best-effort public Myfxbook community retail positioning for 11 FX pairs.

Source displays retail sample only; public snapshots may be delayed by 60 min.
Do not infer live broker flow, executable prices, or trade direction.
Never bypass authentication/paywall.
"""
import concurrent.futures
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

PAIRS = ("AUDUSD","NZDUSD","EURUSD","GBPUSD","USDJPY",
         "AUDJPY","NZDJPY","EURJPY","EURCAD","USDCAD","EURGBP")
BASE = "https://www.myfxbook.com/community/outlook/"
UTC=timezone.utc

def now():
    return datetime.now(UTC).isoformat()

def parse(html, pair):
    result = {"pair": pair, "status": "UNAVAILABLE",
              "long_pct": None, "short_pct": None,
              "long_lots": None, "short_lots": None,
              "long_positions": None, "short_positions": None,
              "source_observation_utc": None,
              "publisher_delay_min": 60,
              "freshness": "PUBLIC_SNAPSHOT_DELAYED_AT_LEAST_60_MINUTES",
              "execution_allowed": False}
    soup=BeautifulSoup(html,"html.parser")
    title = soup.title.get_text(" ",strip=True).upper() if soup.title else ""
    heading = soup.find("h1")
    heading_text = heading.get_text(" ",strip=True).upper() if heading else ""
    # Require a pair-specific page (cannot confuse navigation or cross-pair table)
    if pair not in title and pair not in heading_text:
        result["status"]="PAGE_PAIR_NOT_VERIFIED"
        return result
    text = " ".join(" ".join(soup.stripped_strings).split())
    # Scope to the explicit current-metrics table with LONG and SHORT rows.
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        table_text = " ".join(table.stripped_strings)
        if pair not in table_text:
            continue
        info = {}
        for row in rows:
            cols=[x.get_text(" ",strip=True) for x in row.find_all(["td","th"],recursive=False)]
            if len(cols)<2: continue
            label=cols[0].strip().lower()
            for action in ("short","long"):
                match = re.search(r"\b"+action+r"\b",label)
                if not match: continue
                pct = next((int(x.replace("%","").strip()) for x in cols[1:]
                            if re.fullmatch(r"\s*\d{1,3}\s*%",x)),None)
                if pct is None: continue
                info[action]=pct
        if "long" in info and "short" in info and info["long"] + info["short"] == 100:
            result.update(long_pct=info["long"],short_pct=info["short"],
                          status="PUBLISHED_RETAIL_SAMPLE_DELAYED_60_MIN")
            break
    if result["status"] != "UNAVAILABLE":
        return result
    # Pair-specific published summary paragraph. Strict title/heading match
    # above prevents cross-symbol navigation values leaking into this sample.
    slash=pair[:3]+"/"+pair[3:]
    for paragraph in soup.find_all("p"):
        ptxt=" ".join(" ".join(paragraph.stripped_strings).split())
        if slash not in ptxt.upper() or "forex traders" not in ptxt.lower():
            continue
        hits=re.findall(r"(\d{1,3})\s*%[^%]{0,130}?\bgoing\s+(short|long)\b",ptxt,re.I)
        sides={side.lower():int(pct) for pct,side in hits}
        if len(hits)==2 and set(sides)=={"short","long"} and sides["short"]+sides["long"]==100:
            result.update(short_pct=sides["short"],long_pct=sides["long"],
                          status="PUBLISHED_RETAIL_SAMPLE_DELAYED_60_MIN")
            return result
    # English public prose fallback: numeric percentages require both sides
    # and no claim that the observation clock equals the fetch clock.
    # Match explicitly paired publisher percentages for this page, even when
    # the summary contains line breaks, commas, or an extended narrative.
    short_pattern = (r"(\d{1,3})\s*%\s+of\s+the\s+forex\s+traders"
                     r".{0,120}?\bgoing\s+short\s+with\s+" +
                     re.escape(pair[:3]) + r"\s*/\s*" + re.escape(pair[3:]))
    long_pattern = (r"(\d{1,3})\s*%\s+of\s+the\s+forex\s+traders"
                    r".{0,120}?\bgoing\s+long\s+with\s+" +
                    re.escape(pair[:3]) + r"\s*/\s*" + re.escape(pair[3:]))
    sm = re.search(short_pattern, text, re.I)
    lm = re.search(long_pattern, text, re.I)
    if sm and lm:
        shorts, longs = int(sm.group(1)), int(lm.group(1))
        if shorts+longs == 100 and 0<=shorts<=100:
            result.update(long_pct=longs,short_pct=shorts,
                          status="PUBLISHED_RETAIL_SAMPLE_DELAYED_60_MIN")
            return result
    result["status"]="PUBLIC_PAGE_NO_VERIFIED_POSITIONING"
    return result

def fetch_one(pair):
    url=BASE+pair
    at=now()
    try:
        req=urllib.request.Request(url,headers={
            "User-Agent":"Mozilla/5.0 (compatible; FXResearch/1.0)",
            "Accept":"text/html"})
        with urllib.request.urlopen(req,timeout=16) as res:
            raw=res.read(950_000).decode("utf-8","replace")
        parsed=parse(raw,pair)
    except Exception as e:
        parsed={"pair":pair,"status":"UNAVAILABLE_"+type(e).__name__.upper(),
                "long_pct":None,"short_pct":None,"error":str(e)[:130],
                "publisher_delay_min":60,"execution_allowed":False}
    parsed["source"]="Myfxbook public community outlook"
    parsed["source_url"]=url
    parsed["retrieved_at_utc"]=at
    return pair,parsed

def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        data=dict(pool.map(fetch_one,PAIRS))
    result={"schema_version":1,"collected_at_utc":now(),
            "source":"Myfxbook public community outlook",
            "publisher_delay_min":60,
            "real_time_sentiment":False,
            "real_broker_order_flow":False,
            "status":"DELAYED_PUBLIC_SAMPLE" if any(
                x["status"]=="PUBLISHED_RETAIL_SAMPLE_DELAYED_60_MIN"
                for x in data.values()) else "UNAVAILABLE",
            "pairs":data,
            "note":"May be delayed at least 60 minutes; no true publisher per-pair timestamp. Informational only."}
    Path("fx_retail_positioning.json").write_text(
        json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":result["status"],
                      "covered":sum(x["status"]=="PUBLISHED_RETAIL_SAMPLE_DELAYED_60_MIN"
                                    for x in data.values())}))

if __name__=="__main__":
    main()
