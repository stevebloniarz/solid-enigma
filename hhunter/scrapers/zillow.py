import os
from typing import List

import requests

from models import Listing, SearchParams
from scrapers.base import BaseScraper

# Uses RapidAPI "zillow56" — free tier: 50 req/month
# Subscribe at https://rapidapi.com/apimaker/api/zillow56
_API_HOST = "zillow56.p.rapidapi.com"
_SEARCH_URL = f"https://{_API_HOST}/search"
_DETAIL_URL = f"https://{_API_HOST}/property"

_TYPE_MAP = {
    "Houses": "Houses",
    "Townhomes": "Townhomes",
    "Condos": "Apartments_Condos_Co-ops",
    "Manufactured": "Manufactured",
}


class ZillowScraper(BaseScraper):
    name = "zillow"

    def __init__(self):
        self.api_key = os.getenv("RAPIDAPI_KEY", "")

    def search(self, params: SearchParams) -> List[Listing]:
        if not self.api_key:
            raise RuntimeError(
                "RAPIDAPI_KEY not set. Add it to .env to enable Zillow search."
            )

        home_type = ",".join(
            _TYPE_MAP.get(t, t) for t in params.property_types
        )

        querystring: dict = {
            "location": params.location,
            "output": "json",
            "home_type": home_type,
            "beds_min": str(params.min_beds),
            "baths_min": str(int(params.min_baths)),
        }
        if params.max_beds:
            querystring["beds_max"] = str(params.max_beds)
        if params.min_price:
            querystring["price_min"] = str(params.min_price)
        if params.max_price:
            querystring["price_max"] = str(params.max_price)
        if params.min_sqft:
            querystring["sqft_min"] = str(params.min_sqft)
        if params.max_sqft:
            querystring["sqft_max"] = str(params.max_sqft)

        headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": _API_HOST,
        }

        resp = requests.get(_SEARCH_URL, headers=headers, params=querystring, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        listings = []
        for r in results:
            listing = self._parse_result(r)
            if listing:
                listings.append(listing)
        return listings

    def _parse_result(self, r: dict) -> Listing | None:
        try:
            addr = r.get("address", {})
            zpid = str(r.get("zpid", ""))
            url = r.get("detailUrl", "")
            if not url.startswith("http"):
                url = f"https://www.zillow.com{url}"

            price = self._safe_float(r.get("price") or r.get("unformattedPrice"))
            sqft = self._safe_int(r.get("livingArea"))
            price_per_sqft = None
            if price and sqft and sqft > 0:
                price_per_sqft = round(price / sqft, 2)

            lot_raw = r.get("lotAreaValue")
            lot_unit = r.get("lotAreaUnit", "sqft")
            lot_sqft = None
            if lot_raw:
                lot_sqft = self._safe_int(
                    float(lot_raw) * 43560 if lot_unit == "acres" else lot_raw
                )

            return Listing(
                source="zillow",
                url=url,
                listing_id=zpid,
                address=addr.get("streetAddress", ""),
                city=addr.get("city", ""),
                state=addr.get("state", ""),
                zip_code=addr.get("zipcode", ""),
                price=price,
                beds=self._safe_int(r.get("bedrooms")),
                baths=self._safe_float(r.get("bathrooms")),
                sqft=sqft,
                lot_size_sqft=lot_sqft,
                year_built=self._safe_int(r.get("yearBuilt")),
                property_type=r.get("homeType"),
                price_per_sqft=price_per_sqft,
                days_on_market=self._safe_int(r.get("daysOnZillow")),
                description=r.get("description"),
                image_urls=[r["imgSrc"]] if r.get("imgSrc") else [],
                listed_date=r.get("datePostedString"),
            )
        except Exception:
            return None

    def get_details(self, zpid: str) -> dict:
        """Fetch additional property details (heating, cooling, sewer, etc.)."""
        if not self.api_key:
            return {}
        headers = {
            "X-RapidAPI-Key": self.api_key,
            "X-RapidAPI-Host": _API_HOST,
        }
        resp = requests.get(
            _DETAIL_URL, headers=headers, params={"zpid": zpid}, timeout=30
        )
        if not resp.ok:
            return {}
        return resp.json()

    def enrich_listing(self, listing: Listing) -> Listing:
        """Pull full property details and populate systems fields."""
        details = self.get_details(listing.listing_id)
        if not details:
            return listing

        facts = {}
        for group in details.get("resoFacts", {}).get("atAGlanceFacts", []):
            facts[group.get("factLabel", "").lower()] = group.get("factValue", "")

        listing.heating = facts.get("heating")
        listing.cooling = facts.get("cooling")
        listing.sewer = facts.get("sewer")
        listing.water = facts.get("water")
        listing.parking = facts.get("parking")
        listing.basement = facts.get("basement")

        if not listing.description:
            listing.description = details.get("description")

        imgs = details.get("photos", [])
        if imgs and not listing.image_urls:
            listing.image_urls = [p.get("mixedSources", {}).get("jpeg", [{}])[0].get("url", "") for p in imgs[:5]]
            listing.image_urls = [u for u in listing.image_urls if u]

        return listing
