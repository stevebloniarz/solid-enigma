import os
from datetime import datetime, timedelta
from typing import List

from models import Listing, SearchParams

# AM rush: next Monday 8:00 AM local. PM rush: next Monday 5:00 PM local.
# Google Maps requires departure_time as a Unix timestamp in the future.


def _next_weekday_at(hour: int) -> datetime:
    now = datetime.now()
    days_ahead = 0 - now.weekday()  # Monday = 0
    if days_ahead <= 0:
        days_ahead += 7
    next_monday = now + timedelta(days=days_ahead)
    return next_monday.replace(hour=hour, minute=0, second=0, microsecond=0)


def calculate_commute(listing: Listing, employer_address: str) -> Listing:
    """Populate commute_minutes_am, commute_minutes_pm, commute_distance_miles."""
    try:
        import googlemaps
    except ImportError:
        return listing

    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return listing

    gmaps = googlemaps.Client(key=api_key)
    origin = listing.full_address
    destination = employer_address

    am_time = _next_weekday_at(8)
    pm_time = _next_weekday_at(17)

    try:
        am_result = gmaps.distance_matrix(
            origins=[origin],
            destinations=[destination],
            mode="driving",
            departure_time=am_time,
            traffic_model="best_guess",
        )
        am_element = am_result["rows"][0]["elements"][0]
        if am_element["status"] == "OK":
            listing.commute_minutes_am = round(
                am_element["duration_in_traffic"]["value"] / 60
            )
            listing.commute_distance_miles = round(
                am_element["distance"]["value"] / 1609.34, 1
            )
    except Exception:
        pass

    try:
        pm_result = gmaps.distance_matrix(
            origins=[destination],  # employer → home for PM
            destinations=[origin],
            mode="driving",
            departure_time=pm_time,
            traffic_model="best_guess",
        )
        pm_element = pm_result["rows"][0]["elements"][0]
        if pm_element["status"] == "OK":
            listing.commute_minutes_pm = round(
                pm_element["duration_in_traffic"]["value"] / 60
            )
    except Exception:
        pass

    return listing


def calculate_commutes(listings: List[Listing], params: SearchParams) -> List[Listing]:
    """Calculate commute times for all listings and flag those within limit."""
    for listing in listings:
        calculate_commute(listing, params.employer_address)
        am = listing.commute_minutes_am
        pm = listing.commute_minutes_pm
        worst = max(x for x in [am, pm] if x is not None) if (am or pm) else None
        if worst is not None:
            listing.within_commute_limit = worst <= params.max_commute_minutes
        else:
            listing.within_commute_limit = None
    return listings
