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
    if re.search(r"\bNEUTRAL\b|\bNTRL\b",text):return "NEUTRAL"
    if re.search(r"\bSELL\b",text):return "SELL"
    if re.search(r"\bBUY\b",text):return "BUY"
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


def collect_fxstreet(soup):
    """Read explicit 15m high/low from visible static tables; never infer hidden charts."""
    data={}
    for table in soup.select("table"):
        rows=table.select("tr")
        if not rows:continue
        hdr=["".join(filter(str.isalpha,c.get_text(" ",strip=True).upper())) for c in rows[0].find_all(["th","td"])]
        cols={p:next((j for j,v in enumerate(hdr) if p in v),None) for p in PAIRS}
        lookup={}
        for row in rows[1:]:
            cells=[c.get_text(" ",strip=True) for c in row.find_all(["td","th"])]
            if cells:lookup[" ".join(cells[0].lower().split())]=cells
        hi=lookup.get("15m high") or lookup.get("15min high")
        lo=lookup.get("15m low") or lookup.get("15min low")
        if not hi or not lo:continue
        for pair,j in cols.items():
            if j is None or j>=min(len(hi),len(lo)):continue
            try:
                h=float(hi[j].replace(",",""))
                l=float(lo[j].replace(",",""))
            except ValueError:continue
            if 0<l<=h:
                data[pair]={"5m":{"status":"NOT_OFFERED"},
                            "15m":{"high":h,"low":l,"status":"PUBLISHER_TIME_UNVERIFIED"},
                            "30m":{"status":"NOT_OFFERED"}}
    return data


def diagnose_fxempire(soup):
    """Small safe diagnostics of HTML layout; no page dump."""
    print("fxempire DEBUG tables",len(soup.find_all("table")))
    for a in soup.find_all("a",href=True):
        label=a.get_text(" ",strip=True)
        if any(p[:3]+"/"+p[3:] in label for p in ("USDCAD","EURUSD","AUDUSD")):
            cur=a
            for depth in range(1,6):
                cur=cur.parent
                if cur is None:break
                sample=cur.get_text(" | ",strip=True)[:350]
                print("fxempire DEBUG",label[:55],"ancestor",depth,"tag",cur.name,"classes",str(cur.get("class",[]))[:90],"text",sample)
            break
    script_text=" ".join(t.get_text()[:2000] for t in soup.find_all("script")[:6])
    print("fxempire DEBUG script_count",len(soup.find_all("script")),"contains USD/CAD", "USD/CAD" in script_text)


def collect_empire_dynamic_rows(soup):
    """Fallback for div-based ratings grids, requiring six ordered timeframe cells.

    The public FXEmpire matrix orders columns as 15m,30m,1h,4h,1d,1w.
    Only use the fallback if ratings repeat in paired label/abbreviation
    cells and the row contains exactly one covered currency pair.
    """
    results={}
    for a in soup.find_all("a"):
        title=a.get_text(" ",strip=True)
        symbols=[p for p in PAIRS if p[:3]+"/"+p[3:] in title]
        if len(symbols)!=1:
            continue
        pair=symbols[0]
        for ancestor in list(a.parents)[:9]:
            if ancestor.name in ("body","html"):
                break
            visible=list(ancestor.stripped_strings)
            text=" ".join(visible)
            covered=[p for p in PAIRS if p[:3]+"/"+p[3:] in text]
            if len(set(covered))!=1:
                continue
            # Match only standalone rating labels, never fragments of commentary.
            found=[]
            for item in visible:
                t=" ".join(item.upper().split())
                normalized={"S.BUY":"STRONG BUY","S.SELL":"STRONG SELL",
                            "NTRL":"NEUTRAL"}.get(t,t)
                if normalized in ("BUY","SELL","NEUTRAL","STRONG BUY","STRONG SELL"):
                    found.append(normalized)
            # Two renderings (long + abbreviated) per timeframe cell.
            # Reject unpaired or wrong-length rows rather than shifting columns.
            if len(found)==12 and all(found[i]==found[i+1] for i in range(0,12,2)):
                values=found[::2]
            elif len(found)==6:
                values=found
            else:
                continue
            # First two columns are the 15m and 30m ratings.
            results[pair]={"5m":{"status":"NOT_OFFERED"},
                           "15m":{"rating":values[0],"status":"PUBLISHER_TIME_UNVERIFIED"},
                           "30m":{"rating":values[1],"status":"PUBLISHER_TIME_UNVERIFIED"},
                           "row_verified_by":"six_ordered_15m_30m_1h_4h_daily_weekly_ratings"}
            break
    return results

def main():
    result={"collected_at_utc":now(),"scope":"optional_second_opinion_not_execution_feed","sources":{}}
    for name,url in URLS.items():
        item={"url":url,"status":"UNAVAILABLE","retrieved_at_utc":None,
              "publisher_timestamp_utc":None,"freshness_verified":False,
              "pairs":{},"timeframes":{"5m":"UNAVAILABLE","15m":"UNAVAILABLE","30m":"UNAVAILABLE"}}
        try:
            soup=get_public_html(url)
            item["retrieved_at_utc"]=now()
            print(name,"HTML tables",len(soup.select("table")))
            if name=="fxempire":
                diagnose_fxempire(soup)
                item["pairs"]=collect_fxempire(soup)
                if not item["pairs"]:
                    item["pairs"]=collect_empire_dynamic_rows(soup)
                if item["pairs"]:
                    item["status"]="REFERENCE_ONLY_PUBLISHER_TIMESTAMP_MISSING"
                    item["timeframes"]={"5m":"NOT_OFFERED","15m":"REFERENCE_ONLY","30m":"REFERENCE_ONLY"}
                else:
                    item["status"]="UNAVAILABLE_NO_VERIFIED_TABLE"
            else:
                # FXStreet's chart is interactive and may block automated access.
                # A page that opens is not evidence its confluence values are available.
                item["pairs"]=collect_fxstreet(soup)
                if item["pairs"]:
                    item["status"]="REFERENCE_ONLY_PUBLISHER_TIMESTAMP_MISSING"
                    item["timeframes"]={"5m":"NOT_OFFERED","15m":"REFERENCE_ONLY","30m":"NOT_OFFERED"}
                else:
                    item["status"]="UNAVAILABLE_NO_VERIFIED_NUMERIC_LEVELS"
        except Exception as exc:
            item["status"]="UNAVAILABLE_"+type(exc).__name__.upper()
            item["error"]=str(exc)[:160]
        result["sources"][name]=item
        print(name,item["status"],len(item["pairs"]))
    Path("fx_secondary_sources.json").write_text(json.dumps(result,indent=2),encoding="utf-8")

if __name__=="__main__":
    main()
