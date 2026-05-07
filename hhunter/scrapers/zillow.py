import json
import re
from typing import List
from urllib.parse import quote

from playwright.sync_api import sync_playwright

from models import Listing, SearchParams
from scrapers.base_playwright import PlaywrightScraper


class ZillowScraper(PlaywrightScraper):
    name = "zillow"

    # -------------------------------------------------------------------
    # Public
    # -------------------------------------------------------------------

    def search(self, params: SearchParams) -> List[Listing]:
        url = self._build_search_url(params)

        with sync_playwright() as p:
            browser, context = self._make_context(p)
            page = context.new_page()

            # Collect Zillow's own internal search API responses as they fire
            captured: list[dict] = []

            def _on_response(response):
                if "GetSearchPageState" in response.url:
                    try:
                        captured.append(response.json())
                    except Exception:
                        pass

            page.on("response", _on_response)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                self._dismiss_overlays(page)
                page.wait_for_load_state("networkidle", timeout=20_000)
                self._delay(2, 4)

                if captured:
                    return self._parse_api_data(captured[0])

                # Fallback: extract from the __NEXT_DATA__ script tag
                return self._parse_next_data(page)

            except Exception as e:
                raise RuntimeError(f"Zillow search failed: {e}") from e
            finally:
                browser.close()

    # -------------------------------------------------------------------
    # URL builder
    # -------------------------------------------------------------------

    def _build_search_url(self, params: SearchParams) -> str:
        # Zillow URL format:
        # /homes/for_sale/{location}_rb/{minprice}-{maxprice}_price/{beds}-_beds/{baths}-_baths/
        loc = params.location.replace(", ", "-").replace(",", "-").replace(" ", "-")
        parts = [f"https://www.zillow.com/homes/for_sale/{loc}_rb"]

        if params.min_price and params.max_price:
            parts.append(f"{params.min_price}-{params.max_price}_price")
        elif params.max_price:
            parts.append(f"1-{params.max_price}_price")

        parts.append(f"{params.min_beds}-_beds")

        if params.min_baths >= 1:
            parts.append(f"{int(params.min_baths)}-_baths")

        if params.min_sqft:
            parts.append(f"{params.min_sqft}-_sqft")

        return "/".join(parts) + "/"

    # -------------------------------------------------------------------
    # Parsers
    # -------------------------------------------------------------------

    def _parse_api_data(self, data: dict) -> List[Listing]:
        results = (
            data.get("cat1", {})
                .get("searchResults", {})
                .get("listResults", [])
        )
        return [l for l in (self._parse_result(r) for r in results) if l]

    def _parse_next_data(self, page) -> List[Listing]:
        try:
            raw = page.eval_on_selector("#__NEXT_DATA__", "el => el.textContent")
            data = json.loads(raw)
            results = (
                data.get("props", {})
                    .get("pageProps", {})
                    .get("searchPageState", {})
                    .get("cat1", {})
                    .get("searchResults", {})
                    .get("listResults", [])
            )
        except Exception:
            return []
        return [l for l in (self._parse_result(r) for r in results) if l]

    def _parse_result(self, r: dict) -> Listing | None:
        try:
            zpid = str(r.get("zpid", ""))
            detail_url = r.get("detailUrl", "")
            if detail_url and not detail_url.startswith("http"):
                detail_url = f"https://www.zillow.com{detail_url}"

            raw_price = r.get("unformattedPrice") or r.get("price", 0)
            if isinstance(raw_price, str):
                raw_price = re.sub(r"[^\d.]", "", raw_price)
            price = self._safe_float(raw_price)

            sqft = self._safe_int(r.get("area") or r.get("livingArea"))
            ppsf = round(price / sqft, 2) if (price and sqft) else None

            hdp = r.get("hdpData", {}).get("homeInfo", {})

            return Listing(
                source="zillow",
                url=detail_url,
                listing_id=zpid,
                address=r.get("addressStreet") or r.get("address", ""),
                city=r.get("addressCity") or hdp.get("city", ""),
                state=r.get("addressState") or hdp.get("state", ""),
                zip_code=str(r.get("addressZipcode") or hdp.get("zipcode", "")),
                price=price,
                beds=self._safe_int(r.get("beds")),
                baths=self._safe_float(r.get("baths")),
                sqft=sqft,
                year_built=self._safe_int(hdp.get("yearBuilt")),
                property_type=r.get("homeType") or hdp.get("homeType"),
                price_per_sqft=ppsf,
                days_on_market=self._safe_int(r.get("daysOnZillow")),
                description=r.get("description"),
                image_urls=[r["imgSrc"]] if r.get("imgSrc") else [],
                listed_date=r.get("datePostedString"),
            )
        except Exception:
            return None

    # -------------------------------------------------------------------
    # Detail page enrichment (heating, cooling, sewer, etc.)
    # Navigates to each listing page — use sparingly to avoid rate limits.
    # -------------------------------------------------------------------

    def enrich_listing(self, listing: Listing, context) -> Listing:
        """Fetch the detail page for a single listing and populate systems fields."""
        if not listing.url:
            return listing
        page = context.new_page()
        try:
            page.goto(listing.url, wait_until="domcontentloaded", timeout=30_000)
            self._delay(1.5, 3)
            raw = page.eval_on_selector("#__NEXT_DATA__", "el => el.textContent")
            data = json.loads(raw)

            # gdpClientCache is a JSON-encoded string nested inside __NEXT_DATA__
            cache_raw = self._safe_get(
                data, "props", "pageProps", "componentProps", "gdpClientCache"
            )
            if cache_raw:
                cache = json.loads(cache_raw)
                prop_key = next(iter(cache), None)
                if prop_key:
                    prop = cache[prop_key].get("property", {})
                    reso = prop.get("resoFacts", {})
                    listing.heating = _join(reso.get("heating"))
                    listing.cooling = _join(reso.get("cooling"))
                    listing.sewer = _join(reso.get("sewer"))
                    listing.water = _join(reso.get("water"))
                    listing.parking = _join(reso.get("parkingFeatures"))
                    listing.basement = str(reso.get("hasBasement", ""))
                    if not listing.description:
                        listing.description = prop.get("description")
        except Exception:
            pass
        finally:
            page.close()
        return listing

    def enrich_all(self, listings: List[Listing], max_enrich: int = 20) -> List[Listing]:
        """Open one browser and enrich up to max_enrich listings with detail page data."""
        with sync_playwright() as p:
            browser, context = self._make_context(p)
            try:
                for listing in listings[:max_enrich]:
                    self.enrich_listing(listing, context)
                    self._delay(2, 4)
            finally:
                browser.close()
        return listings


def _join(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, list):
        return ", ".join(str(v) for v in val if v)
    return str(val)
