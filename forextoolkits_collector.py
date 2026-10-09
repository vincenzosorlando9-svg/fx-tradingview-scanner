
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

URL = "https://forextoolkits.com/forex-api/forex_data.json"
TIMEFRAMES = {"M5", "M15", "M30", "H1", "H4", "D1"}

request = urllib.request.Request(
    URL,
    headers={"User-Agent": "Mozilla/5.0"}
)

with urllib.request.urlopen(request, timeout=30) as response:
    data = json.load(response)

pairs = data.get("pairs", {})

if len(pairs) != 28:
    raise ValueError(f"Expected 28 pairs, got {len(pairs)}")

for pair, values in pairs.items():
    frames = values.get("tf", {})
    if not TIMEFRAMES.issubset(frames):
        raise ValueError(f"Missing timeframes for {pair}")

    for timeframe in TIMEFRAMES:
        candles = frames[timeframe]
        lengths = [
            len(candles.get(key, []))
            for key in ("o", "h", "l", "c", "t")
        ]
        if min(lengths) < 14 or len(set(lengths)) != 1:
            raise ValueError(
                f"Invalid candle data: {pair} {timeframe}"
            )

result = {
    "source": URL,
    "collected_at_utc": datetime.now(
        timezone.utc
    ).isoformat(),
    "source_timestamp": data.get("timestamp"),
    "source_server_time": data.get("server_time"),
    "pair_count": len(pairs),
    "timeframes": sorted(TIMEFRAMES),
    "status": "captured_unverified_freshness",
    "pairs": pairs,
}

Path("fx_volatility.json").write_text(
    json.dumps(result, separators=(",", ":")),
    encoding="utf-8"
)

print("Volatility feed saved successfully")
print("Pairs:", len(pairs))
print("Timeframes:", len(TIMEFRAMES))
