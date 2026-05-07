import json
from pathlib import Path
from typing import List

import pandas as pd

from models import Listing

_CSV_COLUMNS = [
    "source",
    "url",
    "address",
    "city",
    "state",
    "zip_code",
    "price",
    "beds",
    "baths",
    "sqft",
    "lot_size_sqft",
    "year_built",
    "property_type",
    "heating",
    "cooling",
    "sewer",
    "water",
    "parking",
    "basement",
    "price_per_sqft",
    "days_on_market",
    "price_assessment",
    "commute_minutes_am",
    "commute_minutes_pm",
    "commute_distance_miles",
    "within_commute_limit",
    "notable_features",
    "listed_date",
    "scraped_at",
    "listing_id",
]


def export_csv(listings: List[Listing], path: str | Path) -> Path:
    path = Path(path)
    rows = [l.to_dict() for l in listings]
    df = pd.DataFrame(rows)
    # Ensure consistent column order, drop any extras
    cols = [c for c in _CSV_COLUMNS if c in df.columns]
    extra = [c for c in df.columns if c not in _CSV_COLUMNS]
    df = df[cols + extra]
    df.to_csv(path, index=False)
    return path


def export_json(listings: List[Listing], path: str | Path) -> Path:
    path = Path(path)
    data = [l.to_json_dict() for l in listings]
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def export_both(listings: List[Listing], stem: str = "listings") -> tuple[Path, Path]:
    csv_path = export_csv(listings, f"{stem}.csv")
    json_path = export_json(listings, f"{stem}.json")
    return csv_path, json_path
