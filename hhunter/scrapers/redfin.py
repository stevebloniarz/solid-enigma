import io
import json
import time
from typing import List

import pandas as pd
import requests

from models import Listing, SearchParams
from scrapers.base import BaseScraper

# Redfin exposes a CSV download endpoint that doesn't require authentication.
# We avoid Playwright here — plain requests with realistic headers work fine.
_CSV_URL = "https://www.redfin.com/stingray/api/gis-csv"
_AUTOCOMPLETE_URL = "https://www.redfin.com/stingray/do/location-autocomplete"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.redfin.com/",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# uipt codes: 1=house, 2=condo, 3=townhome, 8=manufactured
_UIPT = {"Houses": "1", "Condos": "2", "Townhomes": "3", "Manufactured": "8"}


class RedfinScraper(BaseScraper):
    name = "redfin"

    def search(self, params: SearchParams) -> List[Listing]:
        region_id, region_type = self._resolve_location(params.location)
        if not region_id:
            raise RuntimeError(
                f"Could not resolve Redfin region for: {params.location!r}. "
                "Try a 'City, ST' format e.g. 'Boston, MA'."
            )

        uipt = ",".join(_UIPT.get(t, "1") for t in params.property_types)
        query: dict[str, str] = {
            "al": "1",
            "region_id": str(region_id),
            "region_type": str(region_type),
            "uipt": uipt,
            "num_beds": str(params.min_beds),
            "min_beds": str(params.min_beds),
            "num_baths": str(int(params.min_baths)),
            "min_baths": str(int(params.min_baths)),
            "status": "1",
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

        resp = requests.get(_CSV_URL, headers=_HEADERS, params=query, timeout=30)
        resp.raise_for_status()

        csv_text = resp.text
        # Strip the "Download started" header line Redfin prepends
        if csv_text.startswith("Download"):
            csv_text = csv_text[csv_text.index("\n") + 1 :]

        df = pd.read_csv(io.StringIO(csv_text))
        return [
            self._row_to_listing(row)
            for _, row in df.iterrows()
            if pd.notna(row.get("ADDRESS", "")) and str(row.get("ADDRESS", "")).strip()
        ]

    # -------------------------------------------------------------------
    # Location resolution
    # -------------------------------------------------------------------

    def _resolve_location(self, location: str) -> tuple[str | None, str | None]:
        resp = requests.get(
            _AUTOCOMPLETE_URL,
            headers=_HEADERS,
            params={"location": location, "v": "2"},
            timeout=15,
        )
        if not resp.ok:
            return None, None

        # Response is prefixed with "{}&&"
        text = resp.text
        for prefix in ("{}&&", "while(1);"):
            if text.startswith(prefix):
                text = text[len(prefix):]
                break

        try:
            data = json.loads(text)
        except Exception:
            return None, None

        rows = (
            data.get("payload", {})
                .get("sections", [{}])[0]
                .get("rows", [])
        )
        if not rows:
            return None, None

        first = rows[0]
        region_type = first.get("type", "6")
        region_id = first.get("id", {}).get("tableId")
        if not region_id:
            # Fall back to parsing the URL path: /city/30749/MA/Boston
            parts = [p for p in first.get("url", "").split("/") if p]
            region_id = parts[1] if len(parts) > 1 else None

        return str(region_id) if region_id else None, str(region_type)

    # -------------------------------------------------------------------
    # Row → Listing
    # -------------------------------------------------------------------

    def _row_to_listing(self, row) -> Listing:
        price = self._safe_float(row.get("PRICE"))
        sqft = self._safe_int(row.get("SQUARE FEET"))
        ppsf = round(price / sqft, 2) if (price and sqft) else None

        url = str(row.get(
            "URL (SEE https://www.redfin.com/buy-a-home/comparative-market-analysis for info on pricing)", ""
        )).strip()
        if url and not url.startswith("http"):
            url = f"https://www.redfin.com{url}"

        lot_raw = row.get("LOT SIZE")
        lot_sqft = self._safe_int(lot_raw) if pd.notna(lot_raw) else None

        return Listing(
            source="redfin",
            url=url,
            listing_id=str(row.get("MLS#", row.get("ID", ""))),
            address=str(row.get("ADDRESS", "")).strip(),
            city=str(row.get("CITY", "")).strip(),
            state=str(row.get("STATE OR PROVINCE", "")).strip(),
            zip_code=str(row.get("ZIP OR POSTAL CODE", "")).strip(),
            price=price,
            beds=self._safe_int(row.get("BEDS")),
            baths=self._safe_float(row.get("BATHS")),
            sqft=sqft,
            lot_size_sqft=lot_sqft,
            year_built=self._safe_int(row.get("YEAR BUILT")),
            property_type=str(row.get("PROPERTY TYPE", "")),
            price_per_sqft=ppsf,
            days_on_market=self._safe_int(row.get("DAYS ON MARKET")),
            listed_date=str(row.get("SOLD DATE", row.get("LIST DATE", ""))),
        )
