#!/usr/bin/env python3
"""Public Myfxbook retail positioning: reference ONLY, publisher states 60-minute delay.

This is not an API. Reads public community/outlook page without account,
credentials, hidden endpoints, browser automation, or bypassing restrictions.
Missing/ambiguous numbers never count as actual sentiment data.
"""
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from bs4 import BeautifulSoup

URL = "https://www.myfxbook.com/community/outlook"
PAIRS = ("AUDUSD","NZDUSD","EURUSD","GBPUSD","USDJPY","AUDJPY",
         "NZDJPY","EURJPY","EURCAD","USDCAD","EURGBP")

def parse(body, now=None):
    now = now or datetime.now(timezone.utc)
    out = {"collected_at_utc": now.isoformat(), "source": "Myfxbook public Community Outlook",
           "url": URL, "status": "UNAVAILABLE", "pairs": {},
           "reference_delay_minutes_minimum": 60,
           "publisher_quote_timestamp_utc": None,
           "broker_executable": False,
           "method": "VISIBLE_PUBLIC_STATIC_TEXT_MATCHED_LONG_SHORT_PERCENTAGES",
           "disclaimer": "Retail crowd sentiment is delayed; never use as real-time flow"}
    soup = BeautifulSoup(body, "html.parser")
    for tag in soup(["script","style","noscript","template"]):
        tag.decompose()
    text = " ".join(soup.stripped_strings)
    if "sentiment" not in text.lower() and "community" not in text.lower():
        out["status"] = "UNRECOGNIZED_PUBLIC_PAGE"
        return out
    # English public Community Outlook expresses: '63% ... going short ... 37% ... long'.
    # Match ONLY explicit full symbol and both distinct percentages in nearby
    # public UI blocks, not arbitrary percentages on the page.
    for pair in PAIRS:
        blocks = []
        for el in soup.find_all(string=re.compile(r"\b" + pair + r"\b", re.I)):
            p = el.parent
            if not p:
                continue
            for ancestor in list(p.parents)[:5]:
                chunk = " ".join(ancestor.stripped_strings)
                if len(chunk) > 3200:
                    break
                if pair in chunk.upper() and re.search(r"\bshort\b", chunk, re.I) and re.search(r"\blong\b",chunk,re.I):
                    blocks.append(chunk)
                    break
        findings = []
        for block in blocks:
            lower=block.lower()
            mshort = re.search(r"\bshort\b\s*(\d{1,3})\s*%",lower)
            mlong = re.search(r"\blong\b\s*(\d{1,3})\s*%",lower)
            if not mshort or not mlong:
                mshort = re.search(r"\b(\d{1,3})\s*%\s+of\s+(?:the\s+)?(?:forex\s+)?traders.{0,90}\bshort\b",lower)
                mlong = re.search(r"\b(\d{1,3})\s*%\s+of\s+(?:the\s+)?(?:forex\s+)?traders.{0,90}\blong\b",lower)
            if not mshort or not mlong:
                continue
            short,long=int(mshort.group(1)),int(mlong.group(1))
            if 0<=short<=100 and 0<=long<=100 and 98<=long+short<=102:
                findings.append((short,long))
        # Public per-symbol summary is often a single paragraph:
        # "63% ... going short with EUR/USD ... 37% ... going long with EUR/USD".
        slash_pair=pair[:3]+"/"+pair[3:]
        for para in soup.find_all("p"):
            value=" ".join(" ".join(para.stripped_strings).lower().split())
            if slash_pair.lower() not in value:
                continue
            a=re.search(r"(\d{1,3})\s*%\s+of\s+(?:the\s+)?(?:forex\s+)?traders.{0,90}?\bgoing\s+short\b",value)
            b=re.search(r"(\d{1,3})\s*%\s+of\s+(?:the\s+)?(?:forex\s+)?traders.{0,90}?\bgoing\s+long\b",value)
            if a and b:
                short,long=int(a.group(1)),int(b.group(1))
                if 0<=short<=100 and 0<=long<=100 and 98<=short+long<=102:
                    findings.append((short,long))
        if len(set(findings)) == 1 and findings:
            short,long=findings[0]
            out["pairs"][pair]={"short_pct":short,"long_pct":long,
                                "status":"PUBLIC_RETAIL_DELAYED_AT_LEAST_60MIN",
                                "source_url":URL,
                                "market_observation_time":None,
                                "not_institutional_flow":True}
    out["status"] = "PARTIAL_DELAYED_RETAIL_REFERENCE" if out["pairs"] else "UNAVAILABLE_NO_UNAMBIGUOUS_POSITIONS"
    return out

def main():
    now=datetime.now(timezone.utc)
    try:
        req=urllib.request.Request(URL,headers={"User-Agent":"Mozilla/5.0 (compatible; PublicFXResearch/1.0)",
                                              "Accept":"text/html"})
        with urllib.request.urlopen(req,timeout=20) as response:
            html=response.read(2_000_000).decode("utf-8","replace")
        data=parse(html,now)
    except Exception as exc:
        data={"collected_at_utc":now.isoformat(),"source":"Myfxbook",
              "url":URL,"status":"UNAVAILABLE_"+type(exc).__name__.upper(),
              "pairs":{},"error":str(exc)[:150],"reference_delay_minutes_minimum":60,
              "broker_executable":False}
    Path("fx_retail_sentiment.json").write_text(json.dumps(data,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":data["status"],"pairs":list(data["pairs"])}))

if __name__=="__main__":
    main()
