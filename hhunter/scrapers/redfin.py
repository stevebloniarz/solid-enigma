import io
from typing import List

import pandas as pd
import requests

from models import Listing, SearchParams
from scrapers.base import BaseScraper

# Redfin exposes an undocumented CSV download endpoint.
# No auth required, but rate-limit friendly use is expected.
_SEARCH_URL = "https://www.redfin.com/stingray/api/gis-csv"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.redfin.com/",
    "Accept-Language": "en-US,en;q=0.9",
}

# Redfin uipt codes: 1=house, 2=condo, 3=townhome, 8=manufactured
_UIPT_MAP = {
    "Houses": "1",
    "Condos": "2",
    "Townhomes": "3",
    "Manufactured": "8",
}


class RedfinScraper(BaseScraper):
    name = "redfin"

    def search(self, params: SearchParams) -> List[Listing]:
        # Redfin requires a region_id which is location-specific.
        # We first resolve the location to a region_id via their search API.
        region_id, region_type = self._resolve_location(params.location)
        if not region_id:
            raise RuntimeError(
                f"Could not resolve Redfin region for location: {params.location!r}. "
                "Try a more specific city/state combination."
            )

        uipt = ",".join(_UIPT_MAP.get(t, "1") for t in params.property_types)

        query: dict = {
            "al": "1",
            "region_id": region_id,
            "region_type": region_type,
            "uipt": uipt,
            "num_beds": str(params.min_beds),
            "min_beds": str(params.min_beds),
            "num_baths": str(int(params.min_baths)),
            "min_baths": str(int(params.min_baths)),
            "status": "1",  # for sale
            "v": "8",
        }
        if params.max_beds:
            query["max_beds"] = str(params.max_beds)
        if params.min_price:
            query["min_price"] = str(params.min_price)
        if params.max_price:
            query["max_price"] = str(params.max_price)
        if params.min_sqft:
            query["min_sqft"] = str(params.min_sqft)
        if params.max_sqft:
            query["max_sqft"] = str(params.max_sqft)

        resp = requests.get(
            _SEARCH_URL, headers=_HEADERS, params=query, timeout=30
        )
        resp.raise_for_status()

        # Redfin prepends "Download started" text before CSV
        csv_text = resp.text
        if "Download started" in csv_text:
            csv_text = csv_text[csv_text.index("\n") + 1:]

        df = pd.read_csv(io.StringIO(csv_text))
        return [self._row_to_listing(row) for _, row in df.iterrows() if self._row_valid(row)]

    def _resolve_location(self, location: str) -> tuple[str | None, str | None]:
        url = "https://www.redfin.com/stingray/do/location-autocomplete"
        params = {"location": location, "v": "2"}
        resp = requests.get(url, headers=_HEADERS, params=params, timeout=15)
        if not resp.ok:
            return None, None
        # Response is "{}&&" prefixed JSON
        text = resp.text.lstrip("{}&&").strip()
        import json

        try:
            data = json.loads(text)
        except Exception:
            return None, None

        items = data.get("payload", {}).get("sections", [{}])[0].get("rows", [])
        if not items:
            return None, None
        first = items[0]
        url_path = first.get("url", "")
        # Extract region id from url like /city/30749/MA/Boston
        parts = [p for p in url_path.split("/") if p]
        region_type = first.get("type", "6")
        region_id = first.get("id", {}).get("tableId") or (parts[1] if len(parts) > 1 else None)
        return str(region_id) if region_id else None, str(region_type)

    def _row_valid(self, row) -> bool:
        return pd.notna(row.get("ADDRESS", "")) and str(row.get("ADDRESS", "")).strip() != ""

    def _row_to_listing(self, row) -> Listing:
        address = str(row.get("ADDRESS", "")).strip()
        city = str(row.get("CITY", "")).strip()
        state = str(row.get("STATE OR PROVINCE", "")).strip()
        zip_code = str(row.get("ZIP OR POSTAL CODE", "")).strip()
        price = self._safe_float(row.get("PRICE"))
        sqft = self._safe_int(row.get("SQUARE FEET"))
        beds = self._safe_int(row.get("BEDS"))
        baths = self._safe_float(row.get("BATHS"))
        listing_id = str(row.get("MLS#", row.get("ID", "")))
        url = str(row.get("URL (SEE https://www.redfin.com/buy-a-home/comparative-market-analysis for info on pricing)", ""
        )).strip()
        if url and not url.startswith("http"):
            url = f"https://www.redfin.com{url}"

        price_per_sqft = None
        if price and sqft and sqft > 0:
            price_per_sqft = round(price / sqft, 2)

        lot_raw = row.get("LOT SIZE")
        lot_sqft = self._safe_int(lot_raw) if pd.notna(lot_raw) else None

        return Listing(
            source="redfin",
            url=url,
            listing_id=listing_id,
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            price=price,
            beds=beds,
            baths=baths,
            sqft=sqft,
            lot_size_sqft=lot_sqft,
            year_built=self._safe_int(row.get("YEAR BUILT")),
            property_type=str(row.get("PROPERTY TYPE", "")),
            price_per_sqft=price_per_sqft,
            days_on_market=self._safe_int(row.get("DAYS ON MARKET")),
            listed_date=str(row.get("SOLD DATE", row.get("LIST DATE", ""))),
        )
