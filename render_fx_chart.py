"""Render a timestamped EUR/USD 15m SVG candlestick chart from saved OHLC.

Usage: python render_fx_chart.py
Requires fx_volatility.json in the current working directory.
No network access or third-party packages required.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

SOURCE = Path("fx_volatility.json")
DEST = Path("charts/EURUSD_M15.svg")
PAIR, TF = "EURUSD", "M15"


def main():
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    frame = data["pairs"][PAIR]["tf"][TF]
    keys = ("o", "h", "l", "c", "t")
    n = len(frame["t"])
    if n < 20 or any(len(frame[k]) != n for k in keys):
        raise ValueError("Missing or misaligned OHLC timestamps")
    candles = [{k: float(frame[k][i]) for k in ("o", "h", "l", "c")} |
               {"t": int(frame["t"][i])} for i in range(n)]
    for c in candles:
        if c["h"] < max(c["o"], c["c"], c["l"]) or c["l"] > min(c["o"], c["c"]):
            raise ValueError("Invalid candle")
    low = min(c["l"] for c in candles)
    high = max(c["h"] for c in candles)
    pad = max((high - low) * .08, .0002)
    low -= pad
    high += pad
    width, height = 1280, 700
    left, right, top, bottom = 80, 100, 95, 80
    plot_w, plot_h = width - left - right, height - top - bottom

    def y(p):
        return top + (high - p) / (high - low) * plot_h

    def fmt_time(t):
        return datetime.fromtimestamp(t, timezone.utc).strftime("%b %d %H:%M UTC")

    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#101827"/>',
        '<style>text{font-family:Arial,sans-serif;fill:#e2e8f0}</style>',
        '<text x="80" y="39" font-size="25" font-weight="bold">EUR/USD · 15-minute candlesticks</text>',
        f'<text x="80" y="67" font-size="15" fill="#a6b1c5">Last bar: {escape(fmt_time(candles[-1]["t"]))} · source collected {escape(str(data.get("collected_at_utc", "unknown")))}</text>',
    ]
    for j in range(7):
        price = low + (high-low) * j/6
        yy = y(price)
        lines.append(f'<line x1="{left}" y1="{yy:.1f}" x2="{width-right}" y2="{yy:.1f}" stroke="#283548"/>')
        lines.append(f'<text x="{width-right+10}" y="{yy+5:.1f}" font-size="15">{price:.5f}</text>')
    step = plot_w / n
    for i, c in enumerate(candles):
        x = left + (i + .5) * step
        green = c["c"] >= c["o"]
        color = "#38bca2" if green else "#f07079"
        lines.append(f'<line x1="{x:.1f}" y1="{y(c["h"]):.1f}" x2="{x:.1f}" y2="{y(c["l"]):.1f}" stroke="{color}" stroke-width="2"/>')
        yy = min(y(c["o"]), y(c["c"]))
        hh = max(abs(y(c["o"])-y(c["c"])), 1.5)
        lines.append(f'<rect x="{x-step*.31:.1f}" y="{yy:.1f}" width="{step*.62:.1f}" height="{hh:.1f}" fill="{color}"/>')
        if i % 8 == 0 or i == n-1:
            lines.append(f'<text x="{x:.1f}" y="{height-bottom+27}" text-anchor="middle" font-size="12">{escape(datetime.fromtimestamp(c["t"], timezone.utc).strftime("%m/%d %H:%M"))}</text>')
    lines.append(f'<text x="80" y="{height-15}" font-size="13">Historical snapshot; NOT a live executable quote. Candle times shown in UTC.</text>')
    lines.append('</svg>')
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text("\n".join(lines), encoding="utf-8")
    print(f"Saved {DEST} | {n} bars | last close {candles[-1]['c']:.5f} | {fmt_time(candles[-1]['t'])}")


if __name__ == "__main__":
    main()
