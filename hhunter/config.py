import json
import os
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.prompt import Prompt, IntPrompt, Confirm

from models import SearchParams

CONFIG_PATH = Path.home() / ".hhunter" / "config.json"
console = Console()


def _ask_optional_int(prompt: str, default: Optional[int] = None) -> Optional[int]:
    val = Prompt.ask(prompt, default=str(default) if default else "skip")
    if val.strip().lower() in ("skip", "", "none", "n/a"):
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _ask_optional_price(prompt: str) -> Optional[int]:
    val = Prompt.ask(prompt, default="skip")
    if val.strip().lower() in ("skip", "", "none", "n/a"):
        return None
    cleaned = val.replace("$", "").replace(",", "").strip()
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def questionnaire() -> SearchParams:
    console.print("\n[bold cyan]hhunter — House Hunting Setup[/bold cyan]\n")
    console.print("Answer the following questions to configure your search.")
    console.print("Type [bold]skip[/bold] or press Enter to skip optional fields.\n")

    location = Prompt.ask("[bold]Search location[/bold] (city, state or zip code)")
    employer_address = Prompt.ask("[bold]Your employer address[/bold] (full address for commute calculation)")
    max_commute = IntPrompt.ask("[bold]Maximum commute time[/bold] at rush hour (minutes)", default=45)

    console.print("\n[dim]--- Property Requirements ---[/dim]\n")

    min_beds = IntPrompt.ask("Minimum bedrooms", default=2)
    max_beds_raw = _ask_optional_int("Maximum bedrooms (skip for no limit)")
    min_baths_raw = Prompt.ask("Minimum bathrooms", default="1.5")
    try:
        min_baths = float(min_baths_raw)
    except ValueError:
        min_baths = 1.5

    min_sqft = _ask_optional_int("Minimum sq footage (skip for no limit)")
    max_sqft = _ask_optional_int("Maximum sq footage (skip for no limit)")

    console.print("\n[dim]--- Budget ---[/dim]\n")
    min_price = _ask_optional_price("Minimum price (e.g. 300000 or $300,000 — skip for no limit)")
    max_price = _ask_optional_price("Maximum price (e.g. 600000 or $600,000 — skip for no limit)")

    console.print("\n[dim]--- Property Types ---[/dim]\n")
    console.print("Options: Houses, Townhomes, Condos, Manufactured")
    types_raw = Prompt.ask("Property types (comma-separated)", default="Houses")
    property_types = [t.strip() for t in types_raw.split(",") if t.strip()]

    console.print("\n[dim]--- Data Sources ---[/dim]\n")
    use_zillow = Confirm.ask("Search Zillow?", default=True)
    use_redfin = Confirm.ask("Search Redfin?", default=True)
    use_realtor = Confirm.ask("Search Realtor.com?", default=True)
    sources = []
    if use_zillow:
        sources.append("zillow")
    if use_redfin:
        sources.append("redfin")
    if use_realtor:
        sources.append("realtor")
    if not sources:
        sources = ["zillow"]

    params = SearchParams(
        location=location,
        employer_address=employer_address,
        max_commute_minutes=max_commute,
        min_beds=min_beds,
        max_beds=max_beds_raw,
        min_baths=min_baths,
        min_sqft=min_sqft,
        max_sqft=max_sqft,
        min_price=min_price,
        max_price=max_price,
        property_types=property_types,
        sources=sources,
    )

    if Confirm.ask("\nSave these preferences for next time?", default=True):
        save_config(params)
        console.print(f"[dim]Saved to {CONFIG_PATH}[/dim]")

    return params


def save_config(params: SearchParams) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(params.to_dict(), f, indent=2)


def load_config() -> Optional[SearchParams]:
    if not CONFIG_PATH.exists():
        return None
    try:
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        return SearchParams.from_dict(data)
    except Exception:
        return None


def get_params(force_new: bool = False) -> SearchParams:
    if not force_new:
        existing = load_config()
        if existing:
            console.print(f"\n[dim]Loaded saved preferences from {CONFIG_PATH}[/dim]")
            console.print(f"  Location: [bold]{existing.location}[/bold]")
            console.print(f"  Employer: [bold]{existing.employer_address}[/bold]")
            console.print(f"  Max commute: [bold]{existing.max_commute_minutes} min[/bold]")
            console.print(f"  Beds: [bold]{existing.min_beds}+[/bold]  Baths: [bold]{existing.min_baths}+[/bold]")
            if existing.max_price:
                console.print(f"  Price: [bold]up to ${existing.max_price:,}[/bold]")
            use_saved = Confirm.ask("\nUse saved preferences?", default=True)
            if use_saved:
                return existing
    return questionnaire()
