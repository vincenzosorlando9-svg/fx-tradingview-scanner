
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright

PAGE_URL = "https://forextoolkits.com/forex-volatility-bars/"
DATA_URL = "https://forextoolkits.com/forex-api/forex_data.json"

async def main():
    result = {
        "source": DATA_URL,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "unverified",
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(
                PAGE_URL,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            async with page.expect_response(
                lambda r: (
                    DATA_URL.split("?")[0]
                    in r.url
                ),
                timeout=30000,
            ) as response_info:
                await page.reload(
                    wait_until="domcontentloaded"
                )

            response = await response_info.value
            result["http_status"] = response.status

            if response.ok:
                data = await response.json()
                result["status"] = "captured"
                result["data"] = data
                print("JSON successfully captured")
                print("Data type:", type(data).__name__)
                if isinstance(data, dict):
                    print("Top-level keys:", list(data.keys()))
            else:
                result["status"] = "http_error"

        except Exception as exc:
            result["status"] = "error"
            result["error"] = str(exc)
            print("Collection error:", exc)

        finally:
            await browser.close()

    Path("fx_volatility_diagnostic.json").write_text(
        json.dumps(result, indent=2),
        encoding="utf-8",
    )

    print("Final status:", result["status"])

if __name__ == "__main__":
    asyncio.run(main())
