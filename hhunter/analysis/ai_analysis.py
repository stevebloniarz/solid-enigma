"""
AI listing analysis via the /analyze-listings Claude Code skill.

The Playwright crawl produces a JSON file.  After the crawl completes,
run the skill from this repo root:

    /analyze-listings

Claude Code reads the JSON, analyzes every listing (description, price,
images), writes 'notable_features' back, and saves the file — no API key
or subscription beyond your existing Claude Code session.

This module exposes a no-op stub so main.py can still call
analyze_listings(); the real work happens in the skill.
"""

from typing import List
from models import Listing


def analyze_listings(listings: List[Listing], **_) -> List[Listing]:
    """
    Placeholder. Listing analysis is done by the /analyze-listings
    Claude Code skill after the JSON is exported.
    """
    for listing in listings:
        if listing.notable_features is None:
            listing.notable_features = "pending — run /analyze-listings"
    return listings
