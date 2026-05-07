from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime


@dataclass
class SearchParams:
    location: str
    employer_address: str
    max_commute_minutes: int

    min_beds: int = 1
    max_beds: Optional[int] = None
    min_baths: float = 1.0
    max_baths: Optional[float] = None
    min_sqft: Optional[int] = None
    max_sqft: Optional[int] = None
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    property_types: List[str] = field(default_factory=lambda: ["Houses"])

    sources: List[str] = field(default_factory=lambda: ["zillow", "redfin", "realtor"])

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, d: dict) -> "SearchParams":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Listing:
    source: str
    url: str
    listing_id: str

    address: str
    city: str
    state: str
    zip_code: str

    price: Optional[float] = None
    beds: Optional[int] = None
    baths: Optional[float] = None
    sqft: Optional[int] = None
    lot_size_sqft: Optional[int] = None
    year_built: Optional[int] = None
    property_type: Optional[str] = None

    heating: Optional[str] = None
    cooling: Optional[str] = None
    sewer: Optional[str] = None
    water: Optional[str] = None
    parking: Optional[str] = None
    basement: Optional[str] = None

    price_per_sqft: Optional[float] = None
    days_on_market: Optional[int] = None
    price_assessment: Optional[str] = None  # 'at market', 'high', 'low'

    notable_features: Optional[str] = None
    description: Optional[str] = None
    image_urls: List[str] = field(default_factory=list)

    commute_minutes_am: Optional[int] = None
    commute_minutes_pm: Optional[int] = None
    commute_distance_miles: Optional[float] = None
    within_commute_limit: Optional[bool] = None

    listed_date: Optional[str] = None
    scraped_at: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def full_address(self) -> str:
        return f"{self.address}, {self.city}, {self.state} {self.zip_code}"

    def to_dict(self) -> dict:
        d = {}
        for k, v in self.__dict__.items():
            if k == "image_urls":
                d[k] = "|".join(v)
            else:
                d[k] = v
        return d

    def to_json_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}
