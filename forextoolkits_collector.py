
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

URL = "https://forextoolkits.com/forex-volatility-bars/"
TIMEFRAMES = ["M5", "M15", "M30", "H1", "H4", "D1"]

async def main():
    result = {
        "source": URL,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "diagnostic",
        "timeframes": {},
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            viewport={"width": 1440, "height": 1000}
        )

        try:
            response = await page.goto(
                URL, wait_until="domcontentloaded", timeout=60000
            )
            await page.wait_for_timeout(10000)

            result["http_status"] = (
                response.status if response else None
            )

            for timeframe in TIMEFRAMES:
                # Capture visible text before trying tab interaction.
                # This is diagnostic, not validated market data.
                body_before = await page.locator("body").inner_text()

                clicked = False
                try:
                    tab = page.get_by_text(
                        timeframe, exact=True
                    ).first
                    if await tab.count():
                        await tab.click(timeout=5000)
                        await page.wait_for_timeout(2500)
                        clicked = True
                except Exception:
                    pass

                body_after = await page.locator("body").inner_text()

                result["timeframes"][timeframe] = {
                    "tab_clicked": clicked,
                    "page_text_changed": body_before != body_after,
                    "visible_text_excerpt": body_after[:12000],
                }

        except Exception as exc:
            result["status"] = "error"
            result["error"] = str(exc)
        finally:
            await browser.close()

    Path("fx_volatility_diagnostic.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("Diagnostic status:", result["status"])
    print("Timeframes checked:", list(result["timeframes"]))

if __name__ == "__main__":
    asyncio.run(main())
