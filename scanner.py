
import json
from datetime import datetime, timezone
from tradingview_ta import TA_Handler, Interval

PAIRS = [
    "AUDUSD", "NZDUSD", "EURUSD", "GBPUSD",
    "USDJPY", "AUDJPY", "NZDJPY", "EURJPY",
    "EURCAD", "USDCAD", "EURGBP"
]

# User rule: no M5 data collection or M5 signal confirmation. Closed M15/M30
# drive direction; 1H/4H/Daily are context only.
TIMEFRAMES = {
    "15m": Interval.INTERVAL_15_MINUTES,
    "30m": Interval.INTERVAL_30_MINUTES,
    "1H": Interval.INTERVAL_1_HOUR,
    "4H": Interval.INTERVAL_4_HOURS,
    "1D": Interval.INTERVAL_1_DAY,
}

INDICATORS = [
    "close", "RSI", "Stoch.K", "Stoch.D",
    "MACD.macd", "MACD.signal", "ADX", "ATR",
    "EMA10", "EMA20", "EMA50", "EMA100", "EMA200",
    "Recommend.All", "Recommend.MA", "Recommend.Other"
]

results = {
    "collected_at_utc": datetime.now(timezone.utc).isoformat(),
    "pairs": {}
}

for pair in PAIRS:
    results["pairs"][pair] = {}

    for timeframe, interval in TIMEFRAMES.items():
        try:
            handler = TA_Handler(
                symbol=pair,
                screener="forex",
                exchange="FX_IDC",
                interval=interval,
                timeout=15
            )

            analysis = handler.get_analysis()

            results["pairs"][pair][timeframe] = {
                "status": "ok",
                "summary": analysis.summary,
                "indicators": {
                    key: analysis.indicators.get(key)
                    for key in INDICATORS
                }
            }

            print(f"OK: {pair} {timeframe}")

        except Exception as error:
            results["pairs"][pair][timeframe] = {
                "status": "error",
                "message": str(error)
            }
            print(f"ERROR: {pair} {timeframe}: {error}")

with open("fx_technicals.json", "w") as file:
    json.dump(results, file, indent=2)

print("FX technical scan complete.")
