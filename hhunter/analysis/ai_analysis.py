import os
from typing import List

from models import Listing

_SYSTEM_PROMPT = """\
You are a real estate analyst assistant. Given a property listing's description \
and optionally images, identify the most noteworthy aspects — both positive and \
negative. Be concise (2-3 sentences max). Flag anything unusual: flood zones, \
foundation issues, major renovation needs, exceptional value, unusually large \
lot, etc. If nothing stands out, say "No notable concerns or highlights."
"""


def analyze_listing(listing: Listing) -> Listing:
    """Use Claude to summarize notable features from description and images."""
    try:
        import anthropic
    except ImportError:
        listing.notable_features = "anthropic package not installed"
        return listing

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        listing.notable_features = "ANTHROPIC_API_KEY not set — skipping AI analysis"
        return listing

    client = anthropic.Anthropic(api_key=api_key)

    content: list = []

    if listing.description:
        content.append({
            "type": "text",
            "text": f"Property: {listing.full_address}\nPrice: ${listing.price:,.0f}\n"
                    f"Beds: {listing.beds}  Baths: {listing.baths}  Sqft: {listing.sqft}\n\n"
                    f"Listing description:\n{listing.description}",
        })

    for url in listing.image_urls[:3]:
        if url.startswith("http"):
            content.append({
                "type": "image",
                "source": {"type": "url", "url": url},
            })

    if not content:
        listing.notable_features = "No description or images available for analysis"
        return listing

    content.append({"type": "text", "text": "Summarize notable features, red flags, or highlights."})

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        listing.notable_features = msg.content[0].text.strip()
    except Exception as e:
        listing.notable_features = f"AI analysis failed: {e}"

    return listing


def analyze_listings(listings: List[Listing], max_analyze: int = 20) -> List[Listing]:
    """Run AI analysis on up to max_analyze listings (API cost control)."""
    for i, listing in enumerate(listings):
        if i >= max_analyze:
            break
        analyze_listing(listing)
    return listings
