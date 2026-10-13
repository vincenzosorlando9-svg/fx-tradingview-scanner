#!/usr/bin/env python3
"""Collect publicly visible Forex Factory market context, without credentials.
Supplemental only: never use scraped figures as executable live quotes.
"""
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser

PAIRS = ["AUDUSD","NZDUSD","EURUSD","GBPUSD","USDJPY","AUDJPY","NZDJPY","EURJPY","EURCAD","USDCAD","EURGBP"]
class Visible(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden=0
        self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript"):
            self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ("script","style","noscript") and self.hidden:
            self.hidden-=1
    def handle_data(self,data):
        if not self.hidden and data.strip():
            self.parts.append(unescape(data.strip()))
def parse_page(html,pair):
    parser=Visible()
    parser.feed(html)
    text=" ".join(parser.parts)
    title=pair[:3]+"/"+pair[3:]
    # Store only fields that are independently visible and parseable.
    found=bool(re.search(r"\b"+re.escape(title)+r"\\b",text))
    pos=re.search(r"Positions for\s+"+re.escape(title)+r".{0,1000}?(\d{1,3})%\s+(\d+)\s+Traders.{0,100}?(\d+)\s+Traders\s+(\d{1,3})%",text,re.I)
    positions=None
    if pos:
        long_pct,long_n,short_n,short_pct=map(int,pos.groups())
        if long_pct+short_pct==100 and long_n+short_n>0:
            positions={"long_traders_pct":long_pct,"long_traders":long_n,"short_traders_pct":short_pct,"short_traders":short_n,"sample_scope":"Forex Factory displayed traders; not global market positioning"}
    return {"page_recognized":found,"positioning":positions,"price":None,"price_status":"UNAVAILABLE_UNVERIFIED",
            "spread":None,"spread_status":"UNAVAILABLE_UNVERIFIED",
            "momentum":None,"momentum_status":"UNAVAILABLE_UNVERIFIED",
            "note":"Dynamically rendered fields not inferred from blank HTML"}
def main():
    stamp=datetime.now(timezone.utc).isoformat()
    output={"collected_at_utc":stamp,"source":"Forex Factory Market","purpose":"SUPPLEMENTAL_CONTEXT_NOT_EXECUTABLE","pairs":{}}
    success=0
    for pair in PAIRS:
        url="https://www.forexfactory.com/market/"+pair.lower()
        record={"source_url":url,"fetched_at_utc":datetime.now(timezone.utc).isoformat()}
        try:
            req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; FX-research/1.0)"})
            with urllib.request.urlopen(req,timeout=15) as resp:
                body=resp.read(1800000).decode("utf-8","replace")
            record.update(parse_page(body,pair))
            record["status"]="PARTIAL" if record["page_recognized"] else "UNAVAILABLE"
            if record["page_recognized"]:
                success+=1
        except Exception as exc:
            record.update({"status":"UNAVAILABLE","error":type(exc).__name__+": "+str(exc)})
        output["pairs"][pair]=record
    output["recognized_pairs"]=success
    output["status"]="PARTIAL" if success else "UNAVAILABLE"
    path=os.environ.get("FF_MARKETS_OUTPUT","fx_forexfactory_markets.json")
    with open(path+".tmp","w",encoding="utf-8") as file:
        json.dump(output,file,indent=2)
        file.write("\n")
    os.replace(path+".tmp",path)
    print(json.dumps({"status":output["status"],"recognized_pairs":success}))
    # Supplementary web pages may be blocked or JS-only; record UNAVAILABLE
    # in JSON but do not turn missing OPTIONAL context into a failed trading
    # workflow email. The integrated audit must check status, not just age.
    if not success:
        print("FF supplementary positioning: UNAVAILABLE (not a verified signal)")
    return 0
if __name__=="__main__":
    sys.exit(main())
