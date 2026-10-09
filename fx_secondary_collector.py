"""Best-effort public page snapshots. Do not bypass access controls.

FXEmpire: extract 15m/30m ratings ONLY when explicit table headers match.
FXStreet: discover accessibility; no private API or inferred numerical levels.
Missing publisher timestamps => reference-only, never live confirmations.
"""
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

UTC=timezone.utc
PAIRS={"AUDUSD","NZDUSD","EURUSD","GBPUSD","USDJPY","AUDJPY",
       "NZDJPY","EURJPY","EURCAD","USDCAD","EURGBP"}
URLS={
    "fxempire":"https://www.fxempire.com/currencies/technical-analysis",
    "fxstreet":"https://www.fxstreet.com/rates-charts/indicators",
}

def now():
    return datetime.now(UTC).isoformat()

def get_public_html(url):
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 (compatible; FXResearch/1.0)","Accept":"text/html"})
    with urlopen(req,timeout=18) as res:
        content_type=res.headers.get("Content-Type","")
        if "text/html" not in content_type:
            raise ValueError("not_an_html_page")
        return BeautifulSoup(res.read(1200000),"html.parser")

def rating(cell):
    text=" ".join(cell.stripped_strings).upper()
    if "STRONG BUY" in text or "S.BUY" in text:return "STRONG BUY"
    if "STRONG SELL" in text or "S.SELL" in text:return "STRONG SELL"
    if re.search(r"\\bNEUTRAL\\b|\\bNTRL\\b",text):return "NEUTRAL"
    if re.search(r"\\bSELL\\b",text):return "SELL"
    if re.search(r"\\bBUY\\b",text):return "BUY"
    return None

def collect_fxempire(soup):
    output={}
    for table in soup.find_all("table"):
        trs=table.find_all("tr")
        if not trs:continue
        headers=[" ".join(x.stripped_strings).strip().lower().replace(" ","")
                 for x in trs[0].find_all(["th","td"])]
        i15=next((i for i,v in enumerate(headers) if v in ("15min","15m")),None)
        i30=next((i for i,v in enumerate(headers) if v in ("30min","30m")),None)
        if i15 is None or i30 is None:continue
        for tr in trs[1:]:
            cells=tr.find_all(["td","th"])
            if max(i15,i30)>=len(cells):continue
            title=" ".join(cells[0].stripped_strings).upper()
            flat=re.sub("[^A-Z]","",title)
            pair=next((p for p in PAIRS if p in flat),None)
            if not pair:continue
            fifteen=rating(cells[i15])
            thirty=rating(cells[i30])
            if fifteen and thirty:
                output[pair]={"5m":{"status":"NOT_OFFERED"},
                              "15m":{"rating":fifteen,"status":"PUBLISHER_TIME_UNVERIFIED"},
                              "30m":{"rating":thirty,"status":"PUBLISHER_TIME_UNVERIFIED"}}
    return output

def main():
    result={"collected_at_utc":now(),"scope":"optional_second_opinion_not_execution_feed","sources":{}}
    for name,url in URLS.items():
        item={"url":url,"status":"UNAVAILABLE","retrieved_at_utc":None,
              "publisher_timestamp_utc":None,"freshness_verified":False,
              "pairs":{},"timeframes":{"5m":"UNAVAILABLE","15m":"UNAVAILABLE","30m":"UNAVAILABLE"}}
        try:
            soup=get_public_html(url)
            item["retrieved_at_utc"]=now()
            if name=="fxempire":
                item["pairs"]=collect_fxempire(soup)
                if item["pairs"]:
                    item["status"]="REFERENCE_ONLY_PUBLISHER_TIMESTAMP_MISSING"
                    item["timeframes"]={"5m":"NOT_OFFERED","15m":"REFERENCE_ONLY","30m":"REFERENCE_ONLY"}
                else:
                    item["status"]="UNAVAILABLE_NO_VERIFIED_TABLE"
            else:
                # FXStreet's chart is interactive and may block automated access.
                # A page that opens is not evidence its confluence values are available.
                item["status"]="UNAVAILABLE_NO_VERIFIED_TIMESTAMPED_VALUES"
        except Exception as exc:
            item["status"]="UNAVAILABLE_"+type(exc).__name__.upper()
            item["error"]=str(exc)[:160]
        result["sources"][name]=item
        print(name,item["status"],len(item["pairs"]))
    Path("fx_secondary_sources.json").write_text(json.dumps(result,indent=2),encoding="utf-8")

if __name__=="__main__":
    main()
