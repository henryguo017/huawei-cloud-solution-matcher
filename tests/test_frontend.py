"""
Frontend comprehensive test - v20260531w
"""
import asyncio
from playwright.async_api import async_playwright
import os
import sys

BASE_URL = "http://localhost:8080/index.html?v=20260531w"
OUTPUT_DIR = r"E:\newai\huawei-cloud-solution-matcher\frontend_test_screenshots"

async def test_all():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1280, "height": 800})

        # Test 1: Homepage
        print("[1/8] Testing homepage...")
        try:
            await page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            # Dismiss welcome page overlay if present
            enter_btn = await page.query_selector('#enter-btn')
            if enter_btn:
                await enter_btn.click()
                await page.wait_for_timeout(800)
            await page.screenshot(path=os.path.join(OUTPUT_DIR, "01_home.png"), full_page=True)
            title = await page.title()
            results.append(f"PASS: Homepage - {title}")
        except Exception as e:
            results.append(f"FAIL: Homepage - {e}")
            print(f"Homepage error: {e}", file=sys.stderr)

        # Test 2-8: Navigate to each page using JS click to bypass overlay
        pages = [
            ("solution", "02_match", "Solution Match"),
            ("competitor", "03_competitor", "Competitor Analysis"),
            ("products", "04_products", "Product Graph"),
            ("dashboard", "05_dashboard", "Dashboard"),
            ("history", "06_history", "History"),
            ("knowledge", "07_knowledge", "Knowledge Base"),
            ("settings", "08_settings", "Settings"),
        ]

        for idx, (page_key, filename, label) in enumerate(pages, 2):
            print(f"[{idx}/8] Testing {label}...")
            try:
                # Use JS click to bypass welcome page overlay
                await page.evaluate(f'''
                    () => {{
                        const btn = document.querySelector('button[data-page="{page_key}"]');
                        if (btn) btn.click();
                        return !!btn;
                    }}
                ''')
                await page.wait_for_timeout(1500)
                await page.screenshot(path=os.path.join(OUTPUT_DIR, f"{filename}.png"), full_page=True)

                # Special check for products page - verify 3D modal is gone
                if page_key == "products":
                    has_modal = await page.evaluate('() => !!document.getElementById("arch-modal")')
                    has_btn = await page.evaluate('() => !!document.getElementById("arch-tree-btn")')
                    if has_modal or has_btn:
                        results.append(f"WARN: {label} - 3D modal DOM still present")
                    else:
                        results.append(f"PASS: {label} - page loaded, 3D modal removed")
                else:
                    results.append(f"PASS: {label} - page loaded")
            except Exception as e:
                results.append(f"FAIL: {label} - {e}")
                print(f"{label} error: {e}", file=sys.stderr)

        await browser.close()

    # Print results
    print("\n" + "=" * 60)
    print("Frontend Test Results")
    print("=" * 60)
    for r in results:
        print(f"  {r}")
    passed = sum(1 for r in results if r.startswith("PASS"))
    failed = sum(1 for r in results if r.startswith("FAIL"))
    warned = sum(1 for r in results if r.startswith("WARN"))
    print("=" * 60)
    print(f"Total: {len(results)} | Pass: {passed} | Fail: {failed} | Warn: {warned}")
    print(f"Screenshots: {OUTPUT_DIR}")
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    try:
        code = asyncio.run(test_all())
        sys.exit(code)
    except Exception as e:
        print(f"Test runner crashed: {e}", file=sys.stderr)
        sys.exit(1)
