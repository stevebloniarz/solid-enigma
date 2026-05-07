from typing import List

from models import Listing

# Thresholds relative to median price/sqft for the current result set
_LOW_THRESHOLD = 0.88   # more than 12% below median → "low"
_HIGH_THRESHOLD = 1.12  # more than 12% above median → "high"


def assess_prices(listings: List[Listing]) -> List[Listing]:
    """Tag each listing as 'at market', 'low', or 'high' vs. the result-set median."""
    prices_per_sqft = [
        l.price_per_sqft
        for l in listings
        if l.price_per_sqft and l.price_per_sqft > 0
    ]
    if not prices_per_sqft:
        for l in listings:
            l.price_assessment = "unknown"
        return listings

    prices_per_sqft.sort()
    n = len(prices_per_sqft)
    if n % 2 == 1:
        median = prices_per_sqft[n // 2]
    else:
        median = (prices_per_sqft[n // 2 - 1] + prices_per_sqft[n // 2]) / 2

    for listing in listings:
        if not listing.price_per_sqft:
            listing.price_assessment = "unknown"
            continue
        ratio = listing.price_per_sqft / median
        if ratio <= _LOW_THRESHOLD:
            listing.price_assessment = "low"
        elif ratio >= _HIGH_THRESHOLD:
            listing.price_assessment = "high"
        else:
            listing.price_assessment = "at market"

    return listings
