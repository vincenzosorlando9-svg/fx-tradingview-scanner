
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright

URL = "https://forextoolkits.com/forex-volatility-bars/"
TIMEFRAMES = ["M5", "M15", "M30", "H1", "H4", "D1"]

async def main():
    report = {
        "source": URL,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "frames": [],
        "requests": [],
        "timeframes": {},
        "errors": [],
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            viewport={"width": 1440, "height": 1000}
        )

        def record_request(request):
            if len(report["requests"]) >= 300:
                return
            parsed = urlparse(request.url)
            report["requests"].append({
                "method": request.method,
                "host": parsed.netloc,
                "path": parsed.path,
                "resource_type": request.resource_type,
            })

        page.on("request", record_request)

        try:
            response = await page.goto(
                URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            report["http_status"] = (
                response.status if response else None
            )

            await page.wait_for_timeout(12000)

            for frame in page.frames:
                try:
                    text = await frame.locator("body").inner_text(
                        timeout=5000
                    )
                    report["frames"].append({
                        "url": frame.url,
                        "text_excerpt": text[:18000],
                    })
                except Exception as exc:
                    report["errors"].append(str(exc))

            for timeframe in TIMEFRAMES:
                found = False
                clicked = False

                for frame in page.frames:
                    try:
                        locator = frame.get_by_text(
                            timeframe, exact=True
                        ).first

                        if await locator.count():
                            found = True
                            await locator.click(timeout=4000)
                            clicked = True
                            await page.wait_for_timeout(2000)
                            break
                    except Exception:
                        continue

                frame_texts = []
                for frame in page.frames:
                    try:
                        text = await frame.locator(
                            "body"
                        ).inner_text(timeout=5000)
                        frame_texts.append(text[:18000])
                    except Exception:
                        pass

                report["timeframes"][timeframe] = {
                    "control_found": found,
                    "clicked": clicked,
                    "frame_texts": frame_texts,
                }

        except Exception as exc:
            report["errors"].append(str(exc))
        finally:
            await browser.close()

    Path("fx_volatility_diagnostic.json").write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print("HTTP status:", report.get("http_status"))
    print("Frames found:", len(report["frames"]))
    print("Requests observed:", len(report["requests"]))
    print("Errors:", len(report["errors"]))

if __name__ == "__main__":
    asyncio.run(main())
