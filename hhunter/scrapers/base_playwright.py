import os
import random
import time
from typing import Any

from scrapers.base import BaseScraper

# Injected into every page to strip automation fingerprints
_STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined, configurable: true});
    Object.defineProperty(navigator, 'plugins', {
        get: () => [{name:'Chrome PDF Plugin'},{name:'Chrome PDF Viewer'},{name:'Native Client'}]
    });
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    window.chrome = {runtime: {onMessage: {addListener: () => {}}}};
    const _origQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (p) =>
        p.name === 'notifications'
            ? Promise.resolve({state: Notification.permission})
            : _origQuery(p);
"""

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


class PlaywrightScraper(BaseScraper):

    def _make_context(self, playwright, headless: bool | None = None):
        if headless is None:
            headless = os.environ.get("HHUNTER_HEADED", "0") != "1"
        browser = playwright.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
            ],
        )
        context = browser.new_context(
            user_agent=random.choice(_USER_AGENTS),
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
        )
        context.add_init_script(_STEALTH_JS)
        return browser, context

    def _delay(self, lo: float = 1.5, hi: float = 3.5) -> None:
        time.sleep(random.uniform(lo, hi))

    def _dismiss_overlays(self, page) -> None:
        """Dismiss cookie banners and consent dialogs that block content."""
        dismiss_texts = ["Accept", "Accept all", "I agree", "Got it", "OK", "No thanks"]
        for text in dismiss_texts:
            try:
                btn = page.get_by_role("button", name=text, exact=True)
                if btn.is_visible(timeout=500):
                    btn.click()
                    break
            except Exception:
                pass

    def _safe_get(self, d: dict, *keys, default=None) -> Any:
        for k in keys:
            if not isinstance(d, dict):
                return default
            d = d.get(k)
            if d is None:
                return default
        return d
