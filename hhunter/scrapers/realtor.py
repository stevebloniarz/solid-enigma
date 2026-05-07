import json
from typing import List

from playwright.sync_api import sync_playwright

from models import Listing, SearchParams
from scrapers.base_playwright import PlaywrightScraper


class RealtorScraper(PlaywrightScraper):
    name = "realtor"

    def search(self, params: SearchParams) -> List[Listing]:
        url = self._build_search_url(params)

        with sync_playwright() as p:
            browser, context = self._make_context(p)
            page = context.new_page()

            # Realtor.com fires a GraphQL-style search request as it loads.
            # We intercept that instead of parsing the HTML.
            captured: list[dict] = []

            def _on_response(response):
                u = response.url
                if "properties/v3/list" in u or "home_search" in u:
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

                for data in captured:
                    listings = self._parse_api_data(data)
                    if listings:
                        return listings

                # Fallback: parse __NEXT_DATA__
                return self._parse_next_data(page)

            except Exception as e:
                raise RuntimeError(f"Realtor.com search failed: {e}") from e
            finally:
                browser.close()

    # -------------------------------------------------------------------
    # URL builder
    # -------------------------------------------------------------------

    def _build_search_url(self, params: SearchParams) -> str:
        loc = (
            params.location
            .replace(", ", "_")
            .replace(",", "_")
            .replace(" ", "_")
        )
        url = (
            f"https://www.realtor.com/realestateandhomes-search/{loc}"
            f"/beds-{params.min_beds}"
            f"/baths-{int(params.min_baths)}"
        )
        if params.min_price and params.max_price:
            url += f"/price-{params.min_price}-{params.max_price}"
        elif params.max_price:
            url += f"/price-na-{params.max_price}"
        if params.min_sqft:
            url += f"/sqft-{params.min_sqft}"
        return url

    # -------------------------------------------------------------------
    # Parsers
    # -------------------------------------------------------------------

    def _parse_api_data(self, data: dict) -> List[Listing]:
        results = (
            data.get("data", {}).get("home_search", {}).get("results", [])
            or data.get("results", [])
        )
        return [l for l in (self._parse_result(r) for r in results) if l]

    def _parse_next_data(self, page) -> List[Listing]:
        try:
            raw = page.eval_on_selector("#__NEXT_DATA__", "el => el.textContent")
            data = json.loads(raw)
            results = (
                data.get("props", {})
                    .get("pageProps", {})
                    .get("initialReduxState", {})
                    .get("srp", {})
                    .get("normalizedResults", [])
            )
        except Exception:
            return []
        return [l for l in (self._parse_result(r) for r in results) if l]

    def _parse_result(self, r: dict) -> Listing | None:
        try:
            desc = r.get("description", {})
            addr = r.get("location", {}).get("address", {})
            listing_id = str(r.get("property_id", r.get("listing_id", "")))
            permalink = r.get("permalink", "")
            url = (
                f"https://www.realtor.com/realestateandhomes-detail/{permalink}"
                if permalink else ""
            )

            price = self._safe_float(r.get("list_price"))
            sqft = self._safe_int(desc.get("sqft"))
            ppsf = round(price / sqft, 2) if (price and sqft) else None

            photos = r.get("photos") or []
            primary = r.get("primary_photo")
            if isinstance(primary, dict):
                photos = [primary] + list(photos)
            image_urls = [p["href"] for p in photos[:3] if p.get("href")]

            return Listing(
                source="realtor",
                url=url,
                listing_id=listing_id,
                address=addr.get("line", ""),
                city=addr.get("city", ""),
                state=addr.get("state_code", ""),
                zip_code=addr.get("postal_code", ""),
                price=price,
                beds=self._safe_int(desc.get("beds")),
                baths=self._safe_float(
                    desc.get("baths_consolidated") or desc.get("baths")
                ),
                sqft=sqft,
                lot_size_sqft=self._safe_int(desc.get("lot_sqft")),
                year_built=self._safe_int(desc.get("year_built")),
                property_type=desc.get("type"),
                price_per_sqft=ppsf,
                description=desc.get("text"),
                image_urls=image_urls,
                listed_date=r.get("list_date"),
            )
        except Exception:
            return None
