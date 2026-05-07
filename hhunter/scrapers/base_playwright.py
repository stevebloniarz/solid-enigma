import os
import random
import time
from typing import Any

from rich.console import Console
from rich.panel import Panel

from scrapers.base import BaseScraper

_console = Console()

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

# URL substrings that indicate a bot-challenge page
_CAPTCHA_URL_SIGNALS = ["captcha", "challenge", "/cdn-cgi/", "cloudflare.com/cdn-cgi"]

# Page title substrings (case-insensitive)
_CAPTCHA_TITLE_SIGNALS = [
    "just a moment",
    "attention required",
    "access denied",
    "security check",
    "captcha",
    "are you human",
    "verify",
]

# Body text substrings (case-insensitive, checked on first 3 000 chars)
_CAPTCHA_BODY_SIGNALS = [
    "verify you are human",
    "i'm not a robot",
    "complete the security check",
    "checking your browser",
    "enable javascript and cookies to continue",
    "please verify you are a human",
    "press & hold",
    "press and hold",
    "bot or a human",
]

# DOM selectors present on common CAPTCHA / bot-check pages
_CAPTCHA_SELECTORS = [
    "#challenge-form",            # Cloudflare challenge
    ".cf-browser-verification",  # Cloudflare
    ".cf-challenge-running",      # Cloudflare
    ".g-recaptcha",               # Google reCAPTCHA widget
    'iframe[src*="recaptcha"]',   # reCAPTCHA in iframe
    'iframe[src*="hcaptcha"]',    # hCaptcha
    "#px-captcha",                # PerimeterX
    "#px-block-page-container",   # PerimeterX
    "#distil_ident_buttons",      # Distil Networks
]


class PlaywrightScraper(BaseScraper):

    # ------------------------------------------------------------------
    # Browser / context helpers
    # ------------------------------------------------------------------

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
        for text in ["Accept all", "Accept", "I agree", "Got it", "No thanks"]:
            try:
                btn = page.get_by_role("button", name=text, exact=True)
                if btn.is_visible(timeout=500):
                    btn.click()
                    break
            except Exception:
                pass

    # ------------------------------------------------------------------
    # CAPTCHA detection
    # ------------------------------------------------------------------

    def _is_captcha_page(self, page) -> bool:
        """Return True if the current page appears to be a bot/CAPTCHA challenge."""
        try:
            url = page.url.lower()
            if any(s in url for s in _CAPTCHA_URL_SIGNALS):
                return True

            title = (page.title() or "").lower()
            if any(s in title for s in _CAPTCHA_TITLE_SIGNALS):
                return True

            for sel in _CAPTCHA_SELECTORS:
                try:
                    if page.query_selector(sel):
                        return True
                except Exception:
                    pass

            body = (page.inner_text("body")[:3_000]).lower()
            if any(s in body for s in _CAPTCHA_BODY_SIGNALS):
                return True

        except Exception:
            pass

        return False

    # ------------------------------------------------------------------
    # CAPTCHA handling
    # ------------------------------------------------------------------

    def _open_page_with_captcha_retry(
        self,
        playwright,
        url: str,
        on_response=None,
        captured: list | None = None,
        site_name: str = "the site",
    ) -> tuple:
        """
        Open a browser, navigate to url, and handle CAPTCHAs automatically.

        - If CAPTCHA is detected while headless:  the browser is relaunched
          headed (visible) so the user can solve it in the window.
        - If CAPTCHA is detected while headed:  execution is simply paused
          until the user presses Enter after solving.

        on_response: callable registered as the page 'response' handler
                     before each navigation attempt.
        captured:    mutable list used by on_response; cleared automatically
                     when the browser is relaunched to discard stale data.

        Returns (browser, context, page).
        """
        headless = os.environ.get("HHUNTER_HEADED", "0") != "1"

        browser, context = self._make_context(playwright, headless=headless)
        page = context.new_page()
        if on_response:
            page.on("response", on_response)

        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        self._dismiss_overlays(page)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass
        self._delay()

        if not self._is_captcha_page(page):
            return browser, context, page

        # ── CAPTCHA detected ──────────────────────────────────────────
        if headless:
            _console.print(
                Panel(
                    f"[bold yellow]CAPTCHA detected on [cyan]{site_name}[/cyan].[/bold yellow]\n\n"
                    "hhunter is switching to a [bold]visible browser window[/bold] "
                    "so you can solve it.\n"
                    "The window will open in a moment…",
                    title="[bold red]🔒 Bot check[/bold red]",
                    border_style="yellow",
                )
            )
            browser.close()
            if captured is not None:
                captured.clear()

            # Relaunch headed
            browser, context = self._make_context(playwright, headless=False)
            page = context.new_page()
            if on_response:
                page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            self._dismiss_overlays(page)
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass

        # Whether we just relaunched headed or were already headed, pause
        # if a CAPTCHA is still showing.
        if self._is_captcha_page(page):
            _console.print(
                Panel(
                    f"[bold]Solve the CAPTCHA in the browser window[/bold] "
                    f"for [cyan]{site_name}[/cyan].\n\n"
                    "Steps:\n"
                    "  1. Complete the challenge in the browser that opened\n"
                    "  2. Wait for the normal listing page to load\n"
                    "  3. Press [bold green]Enter[/bold green] here to continue",
                    title="[bold red]🔒 Action required[/bold red]",
                    border_style="red",
                )
            )
            input()  # block until user presses Enter
            try:
                page.wait_for_load_state("networkidle", timeout=30_000)
            except Exception:
                pass
            self._delay(1, 2)

        return browser, context, page

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def _safe_get(self, d: dict, *keys, default=None) -> Any:
        for k in keys:
            if not isinstance(d, dict):
                return default
            d = d.get(k)
            if d is None:
                return default
        return d
