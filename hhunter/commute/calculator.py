import re
import time
import random
from datetime import datetime, timedelta
from typing import List, Optional
from urllib.parse import quote

from models import Listing, SearchParams

_STEALTH_JS = "Object.defineProperty(navigator, 'webdriver', {get: () => undefined, configurable: true});"

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _next_monday_8am() -> datetime:
    now = datetime.now()
    days = (7 - now.weekday()) % 7 or 7  # days until next Monday
    return now.replace(hour=8, minute=0, second=0, microsecond=0) + timedelta(days=days)


def _parse_duration(text: str) -> Optional[int]:
    """Convert '1 hr 23 min' or '45 min' to total minutes."""
    text = text.lower()
    hours = int(m.group(1)) if (m := re.search(r"(\d+)\s*hr", text)) else 0
    mins = int(m.group(1)) if (m := re.search(r"(\d+)\s*min", text)) else 0
    return hours * 60 + mins if (hours or mins) else None


def _parse_miles(text: str) -> Optional[float]:
    m = re.search(r"([\d.,]+)\s*mi\b", text)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def _read_route_info(page) -> tuple[Optional[int], Optional[float]]:
    """
    Extract duration and distance from a Google Maps directions page.
    Maps changes its CSS classes frequently, so we try several approaches.
    """
    time.sleep(3)  # let traffic data load

    # Strategy 1: aria-label on the route summary container
    try:
        for sel in [
            '[aria-label*="min"]',
            '[aria-label*="hour"]',
            '.section-directions-trip-duration',
            '.delay-light', '.delay-moderate', '.delay-heavy',
        ]:
            el = page.query_selector(sel)
            if el:
                label = el.get_attribute("aria-label") or el.inner_text()
                if re.search(r"\d+\s*(hr|min)", label, re.I):
                    mins = _parse_duration(label)
                    if mins:
                        # Try to grab distance from nearby text
                        dist_text = page.content()
                        dist = _parse_miles(dist_text)
                        return mins, dist
    except Exception:
        pass

    # Strategy 2: scan all text nodes on the page for a duration pattern
    try:
        content = page.inner_text("body")
        # Look for patterns like "23 min" or "1 hr 10 min" near the top of the page
        matches = re.findall(r"\d+\s*hr\s*\d+\s*min|\d+\s*min", content)
        if matches:
            # Pick the first plausible commute duration (5–300 min)
            for m in matches:
                mins = _parse_duration(m)
                if mins and 5 <= mins <= 300:
                    dist = _parse_miles(content)
                    return mins, dist
    except Exception:
        pass

    return None, None


def _set_departure_time(page, am: bool) -> None:
    """
    Attempt to click the 'Leave now' → 'Depart at' picker and set a
    weekday rush-hour time. Best-effort: Maps UI changes unpredictably.
    """
    try:
        # Look for the departure time toggle
        for sel in [
            'button[data-value="0"]',      # "Leave now"
            '[aria-label*="Leave now"]',
            '[aria-label*="Depart"]',
            'button:has-text("Leave now")',
        ]:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                btn.click()
                time.sleep(0.5)
                break

        # Select "Depart at"
        for sel in ['[data-value="1"]', 'li:has-text("Depart at")', '[aria-label*="Depart at"]']:
            opt = page.query_selector(sel)
            if opt and opt.is_visible():
                opt.click()
                time.sleep(0.5)
                break

        # Set time: fill the time input if it appears
        time_input = page.query_selector('input[aria-label*="time" i], input[type="time"]')
        if time_input:
            target = "8:00 AM" if am else "5:00 PM"
            time_input.triple_click()
            time_input.type(target)
            page.keyboard.press("Enter")
            time.sleep(1)
    except Exception:
        pass  # Fall back to whatever time Maps shows


class _MapsSession:
    """Holds a single Playwright browser across all commute lookups."""

    def __init__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().__enter__()
        browser = self._pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled", "--disable-dev-shm-usage"],
        )
        self._context = browser.new_context(
            user_agent=_UA,
            viewport={"width": 1440, "height": 900},
            locale="en-US",
        )
        self._context.add_init_script(_STEALTH_JS)
        self._browser = browser

    def get_commute(
        self, origin: str, destination: str, am: bool = True
    ) -> tuple[Optional[int], Optional[float]]:
        page = self._context.new_page()
        try:
            o = quote(origin)
            d = quote(destination)
            url = f"https://www.google.com/maps/dir/{o}/{d}/"
            page.goto(url, wait_until="domcontentloaded", timeout=40_000)

            # Dismiss cookie/consent overlays (common outside the US)
            for text in ["Accept all", "Accept", "I agree", "Reject all"]:
                try:
                    btn = page.get_by_role("button", name=text, exact=True)
                    if btn.is_visible(timeout=600):
                        btn.click()
                        time.sleep(0.3)
                        break
                except Exception:
                    pass

            _set_departure_time(page, am)
            mins, dist = _read_route_info(page)
            return mins, dist
        except Exception:
            return None, None
        finally:
            page.close()
            time.sleep(random.uniform(1.5, 3))

    def close(self):
        self._browser.close()
        self._pw.__exit__(None, None, None)


def calculate_commutes(listings: List[Listing], params: SearchParams) -> List[Listing]:
    """
    Calculate rush-hour commute for all listings using a single browser session.
    AM = home → work (8 AM departure).  PM = work → home (5 PM departure).
    """
    session = _MapsSession()
    try:
        for listing in listings:
            origin = listing.full_address
            dest = params.employer_address
            if not origin.strip() or not dest.strip():
                continue

            am_min, dist = session.get_commute(origin, dest, am=True)
            pm_min, _ = session.get_commute(dest, origin, am=False)

            listing.commute_minutes_am = am_min
            listing.commute_minutes_pm = pm_min
            listing.commute_distance_miles = dist

            worst = max((x for x in [am_min, pm_min] if x is not None), default=None)
            listing.within_commute_limit = (
                worst <= params.max_commute_minutes if worst is not None else None
            )
    finally:
        session.close()

    return listings
