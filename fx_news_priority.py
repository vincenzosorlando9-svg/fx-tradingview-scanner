#!/usr/bin/env python3
"""Fast, keyless, APPROVED-source FX headline priority watch.

This is a news-to-price-review queue, never a directional vote or order.
Published clock and first collector sighting are separate; missing Reuters
coverage must never be treated as evidence that no market news occurred.
"""
import concurrent.futures
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fx_macro_collector import NEWS_URLS, PAIRS, get, parse_news

UTC = timezone.utc
FILE = Path("fx_news_priority.json")
CENTRAL_BANK_WORDS = (
    "bank of japan", "boj", "reserve bank of australia", "rba",
    "federal reserve", "fomc", "fed chair", "fed governor",
    "bank of england", "boe", "european central bank", "ecb",
    "bank of canada", "boc", "reserve bank of new zealand", "rbnz",
    "monetary policy", "central bank", "intervention", "rate hike",
    "rate cut", "interest rate", "interest-rate", "rate decision",
    "policy meeting",
)
EVENT_WORDS = ("cpi", "ppi", "inflation", "jobs", "employment",
               "payrolls", "gdp", "retail sales", "bond yields", "treasury yields")


def parse_utc(value):
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d.astimezone(UTC) if d.tzinfo else None
    except (TypeError, ValueError):
        return None


def headline_priority(headline, now, first_seen=None):
    published = parse_utc(headline.get("published_at_utc"))
    title = str(headline.get("title") or "").strip()
    url = str(headline.get("url") or "")
    if not published or not url.startswith("https://") or not title:
        return None
    age = (now - published).total_seconds() / 60
    if not -3 <= age <= 120:
        return None
    lower = title.lower()
    typ = ("CENTRAL_BANK_POLICY" if any(x in lower for x in CENTRAL_BANK_WORDS)
           else "MACRO_DATA_OR_YIELD" if any(x in lower for x in EVENT_WORDS)
           else "GENERAL")
    currencies = set(headline.get("currencies") or [])
    pairs = [p for p in PAIRS if (
        p[:3] in currencies or p[3:] in currencies or
        ("CNY" in currencies and ("AUD" in p or "NZD" in p)))]
    if not pairs:
        return None
    return {
        "provider": headline.get("provider"),
        "title": title[:220],
        "url": url,
        "published_at_utc": published.isoformat(),
        "first_seen_at_utc": first_seen or now.isoformat(),
        "publisher_age_minutes": round(age, 1),
        "source_latency_to_first_seen_minutes": round(
            (parse_utc(first_seen or now.isoformat()) - published).total_seconds() / 60, 1),
        "type": typ,
        "priority": "HIGH_POLICY_REACTION_CHECK" if typ == "CENTRAL_BANK_POLICY" else
                    "MEDIUM_RELEASE_REACTION_CHECK" if typ == "MACRO_DATA_OR_YIELD" else
                    "CONTEXT",
        "currencies": sorted(currencies),
        "affected_pairs": pairs,
        "headline_direction": "UNDETERMINED",
        "market_reaction": "NOT_VERIFIED",
        "broker_execution_allowed": False,
    }


def make_watch(news_sources, previous=None, now=None):
    now = now or datetime.now(UTC)
    previous = previous or {}
    seen = {x.get("url"): x.get("first_seen_at_utc")
            for x in previous.get("recent_headlines", [])
            if parse_utc(x.get("first_seen_at_utc"))}
    statuses, newest = {}, {}
    for name in NEWS_URLS:
        feed = news_sources.get(name) or {}
        statuses[name] = feed.get("status") or "UNAVAILABLE"
        for item in feed.get("articles") or []:
            row = headline_priority({**item, "provider": name},
                                    now, seen.get(item.get("url")))
            if row:
                newest[row["url"]] = row
    headlines = sorted(newest.values(),
        key=lambda x: (x["priority"] != "HIGH_POLICY_REACTION_CHECK",
                       x["priority"] == "CONTEXT", -parse_utc(x["published_at_utc"]).timestamp()))
    gaps = [name + ":" + status for name, status in statuses.items()
            if status != "DATED_HEADLINES"]
    by_pair = {}
    for pair in PAIRS:
        items = [x for x in headlines if pair in x["affected_pairs"]]
        policy = [x for x in items if x["priority"] == "HIGH_POLICY_REACTION_CHECK"]
        by_pair[pair] = {
            "status": "POLICY_REACTION_CHECK" if policy else
                      "HEADLINES_PRESENT" if items else
                      "NO_RECENT_RETRIEVABLE_APPROVED_NEWS",
            "policy_headlines": policy[:5],
            "news_headlines": items[:8],
            "source_coverage_incomplete": bool(gaps),
            "no_news_is_not_proof_of_no_catalyst": True,
            "directional_vote": "NONE",
            "price_reaction_requires_completed_15m30m_candles": True,
        }
    return {
        "schema_version": 1,
        "generated_at_utc": now.isoformat(),
        "target_refresh_minutes": 5,
        "actual_actions_schedule_not_guaranteed": True,
        "approved_source_names": sorted(NEWS_URLS),
        "source_statuses": statuses,
        "source_coverage_gaps": gaps,
        "any_provider_unavailable": bool(gaps),
        "recent_headlines": headlines[:60],
        "pairs": by_pair,
        "no_new_sources": True,
        "no_headline_buy_sell_votes": True,
        "no_trades_or_alerts": True,
    }


def main():
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {name: pool.submit(get, url, 9) for name, url in NEWS_URLS.items()}
        feeds = {name: parse_news(job.result(), name) for name, job in jobs.items()}
    try:
        previous = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    except (ValueError, OSError):
        previous = {}
    watch = make_watch(feeds, previous=previous)
    FILE.write_text(json.dumps(watch, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    print(json.dumps({"result": "PUBLISHED", "provider_statuses": watch["source_statuses"],
                      "priority_policy_headlines": sum(x["priority"]=="HIGH_POLICY_REACTION_CHECK"
                                                       for x in watch["recent_headlines"]),
                      "pairs": len(watch["pairs"]), "missing_coverage": watch["source_coverage_gaps"]}))


if __name__ == "__main__":
    main()
