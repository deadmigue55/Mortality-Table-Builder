"""Opens the public dashboard in a real browser, waking it if Streamlit put it to sleep.

Streamlit Community Cloud sleeps a free app after about 12 hours without a visitor, and the next
visitor then waits behind a "get this app back up" page. A plain HTTP request does not count as a
visit; a browser that loads the page and opens its websocket does. This script is that browser.

It exits with an error (so the workflow fails and GitHub emails the owner) if the app is still not
showing its sidebar after the wait, or if the page reports "Error running app".

Usage:  python scripts/keep_alive.py [url]
"""

import sys

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://mortality-table-builder.streamlit.app/"
WAKE_BUTTON = "Yes, get this app back up!"
WAKE_TIMEOUT_MS = 4 * 60 * 1000  # a cold start installs the environment: allow several minutes


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.goto(URL, wait_until="domcontentloaded", timeout=120_000)

        button = page.get_by_role("button", name=WAKE_BUTTON)
        try:
            button.wait_for(state="visible", timeout=15_000)
            print("The app was asleep: waking it")
            button.click()
        except PlaywrightTimeout:
            print("The app was already awake")

        # Streamlit renders inside an iframe on the hosted site, so look for the sidebar anywhere
        try:
            page.frame_locator("iframe").first.locator("[data-testid=stSidebar]").wait_for(
                state="visible", timeout=WAKE_TIMEOUT_MS
            )
        except PlaywrightTimeout:
            try:
                page.locator("[data-testid=stSidebar]").wait_for(state="visible", timeout=30_000)
            except PlaywrightTimeout:
                print("FAIL: the dashboard did not show its sidebar")
                print(page.inner_text("body")[:600])
                return 1

        text = page.inner_text("body")
        frames = " ".join(f.locator("body").inner_text() for f in page.frames[1:] if f.url)
        if "Error running app" in text + frames:
            print("FAIL: the page reports 'Error running app'")
            return 1
        print("OK: the dashboard is up")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
