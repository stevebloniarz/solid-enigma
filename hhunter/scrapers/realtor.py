import os
from typing import List

import requests

from models import Listing, SearchParams
from scrapers.base import BaseScraper

# Uses RapidAPI "realty-in-us" — free tier available
# Subscribe at https://rapidapi.com/apidojo/api/realty-in-us
_API_HOST = "realty-in-us.p.rapidapi.com"
_SEARCH_URL = f"https://{_API_HOST}/properties/v3/list"

_TYPE_MAP = {
    "Houses": "single_family",
    "Townhomes": "townhomes",
    "Condos": "condos",
    "Manufactured": "mobile",
}


class RealtorScraper(BaseScraper):
    name = "realtor"

    def __init__(self):
        self.api_key = os.getenv("RAPIDAPI_KEY", "")

    def search(self, params: SearchParams) -> List[Listing]:
        if not self.api_key:
            raise RuntimeError(
                "RAPIDAPI_KEY not set. Add it to .env to enable Realtor.com search."
            )

        prop_types = [_TYPE_MAP.get(t, "single_family") for t in params.property_types]

        payload = {
            "limit": 42,
            "offset": 0,
            "postal_code": params.location if params.location.isdigit() else None,
            "city": None if params.location.isdigit() else params.location.split(",")[0].strip(),
            "state_code": None,
            "beds_min": params.min_beds,
            "baths_min": int(params.min_baths),
            "list_price_min": params.min_price,
            "list_price_max": params.max_price,
            "sqft_min": params.min_sqft,
            "sqft_max": params.max_sqft,
            "prop_type": prop_types,
            "status": ["for_sale"],
            "sort": {"direction": "desc", "field": "list_date"},
        }
        # Clean None values
        payload = {k: v for k, v in payload.items() if v is not None}
        # Parse city/state from "City, ST" format
        if not params.location.isdigit() and "," in params.location:
            parts = params.location.split(",")
            payload["city"] = parts[0].strip()
            if len(parts) > 1:
                payload["state_code"] = parts[1].strip()[:2].upper()

        headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": _API_HOST,
            "Content-Type": "application/json",
        }

        resp = requests.post(_SEARCH_URL, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("data", {}).get("home_search", {}).get("results", [])
        listings = []
        for r in results:
            listing = self._parse_result(r)
            if listing:
                listings.append(listing)
        return listings

    def _parse_result(self, r: dict) -> Listing | None:
        try:
            loc = r.get("location", {})
            addr = loc.get("address", {})
            listing_id = r.get("property_id", "")
            permalink = r.get("permalink", "")
            url = f"https://www.realtor.com/realestateandhomes-detail/{permalink}" if permalink else ""

            desc = r.get("description", {})
            price = self._safe_float(r.get("list_price"))
            sqft = self._safe_int(desc.get("sqft"))
            price_per_sqft = None
            if price and sqft and sqft > 0:
                price_per_sqft = round(price / sqft, 2)

            photos = r.get("photos", [])
            image_urls = [p.get("href", "") for p in photos[:5] if p.get("href")]

            tags = r.get("tags", [])
            systems_info = ", ".join(tags) if tags else None

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
                baths=self._safe_float(desc.get("baths_consolidated") or desc.get("baths")),
                sqft=sqft,
                lot_size_sqft=self._safe_int(desc.get("lot_sqft")),
                year_built=self._safe_int(desc.get("year_built")),
                property_type=desc.get("type"),
                heating=desc.get("heating") or (systems_info if "heat" in (systems_info or "").lower() else None),
                cooling=desc.get("cooling") or (systems_info if "cool" in (systems_info or "").lower() else None),
                parking=desc.get("garage") and f"{desc.get('garage')} car garage",
                price_per_sqft=price_per_sqft,
                days_on_market=self._safe_int(r.get("list_date_delta")),
                description=desc.get("text"),
                image_urls=image_urls,
                listed_date=r.get("list_date"),
            )
        except Exception:
            return None
