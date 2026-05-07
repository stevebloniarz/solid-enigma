#!/usr/bin/env python3
"""hhunter — CLI house hunting aggregator."""

import os
import sys
from datetime import datetime

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

load_dotenv()

console = Console()


def _run_search(params, no_commute: bool, enrich: bool, headed: bool) -> list:
    from scrapers import SCRAPERS
    from analysis.price import assess_prices
    from analysis.ai_analysis import analyze_listings
    from commute.calculator import calculate_commutes

    # Expose headed mode to Playwright scrapers via env so they can read it
    if headed:
        os.environ["HHUNTER_HEADED"] = "1"
    else:
        os.environ.pop("HHUNTER_HEADED", None)

    all_listings = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:

        for source in params.sources:
            task = progress.add_task(f"Searching {source} (Playwright)...", total=None)
            try:
                scraper = SCRAPERS[source]()
                results = scraper.search(params)
                all_listings.extend(results)
                progress.update(
                    task,
                    description=f"[green]{source}: {len(results)} listings[/green]",
                )
            except Exception as e:
                progress.update(task, description=f"[red]{source} failed: {e}[/red]")
            finally:
                progress.stop_task(task)

        if not all_listings:
            return []

        # Optional: fetch Zillow detail pages for heating/cooling/sewer
        if enrich and "zillow" in params.sources:
            from scrapers.zillow import ZillowScraper
            zillow_listings = [l for l in all_listings if l.source == "zillow"]
            if zillow_listings:
                task = progress.add_task(
                    f"Enriching {len(zillow_listings)} Zillow listings (detail pages)...",
                    total=None,
                )
                ZillowScraper().enrich_all(zillow_listings)
                progress.stop_task(task)

        task = progress.add_task("Assessing prices vs. median...", total=None)
        all_listings = assess_prices(all_listings)
        progress.stop_task(task)

        if not no_commute:
            task = progress.add_task(
                f"Calculating rush-hour commutes via Google Maps ({len(all_listings)} listings)...",
                total=None,
            )
            all_listings = calculate_commutes(all_listings, params)
            progress.stop_task(task)

        # Mark listings for analysis by the /analyze-listings Claude Code skill
        analyze_listings(all_listings)

    return all_listings


def _print_table(listings: list, max_commute: int) -> None:
    table = Table(
        title=f"hhunter — {len(listings)} listings",
        show_lines=True,
        header_style="bold cyan",
    )
    table.add_column("Source", style="dim", width=8)
    table.add_column("Address")
    table.add_column("Price", justify="right")
    table.add_column("Bd/Ba/Sqft", justify="center")
    table.add_column("$/sqft", justify="right")
    table.add_column("Market", justify="center")
    table.add_column("AM rush", justify="right")
    table.add_column("PM rush", justify="right")
    table.add_column("DOM", justify="right")
    table.add_column("URL", style="dim")

    for l in listings:
        price_str = f"${l.price:,.0f}" if l.price else "-"
        bed_bath = f"{l.beds or '?'}/{l.baths or '?'}/{l.sqft:,}" if l.sqft else f"{l.beds or '?'}/{l.baths or '?'}/-"
        ppsf = f"${l.price_per_sqft:.0f}" if l.price_per_sqft else "-"

        pa = l.price_assessment or "-"
        pa_fmt = {"low": "[green]low[/green]", "high": "[red]high[/red]"}.get(pa, pa)

        am_min = l.commute_minutes_am
        pm_min = l.commute_minutes_pm
        am_str = f"{am_min}m" if am_min is not None else "-"
        pm_str = f"{pm_min}m" if pm_min is not None else "-"
        worst = max((x for x in [am_min, pm_min] if x is not None), default=None)
        if worst is not None and worst > max_commute:
            am_str = f"[red]{am_str}[/red]"
            pm_str = f"[red]{pm_str}[/red]"

        dom = str(l.days_on_market) if l.days_on_market is not None else "-"
        short_addr = f"{l.address}, {l.city}"
        url = (l.url[:52] + "…") if len(l.url) > 53 else l.url

        table.add_row(l.source, short_addr, price_str, bed_bath, ppsf, pa_fmt, am_str, pm_str, dom, url)

    console.print(table)


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    if ctx.invoked_subcommand is None:
        ctx.invoke(search)


@cli.command()
@click.option("--new", is_flag=True, help="Ignore saved preferences and re-run setup.")
@click.option("--no-commute", is_flag=True, help="Skip Google Maps commute calculation.")
@click.option("--enrich", is_flag=True, help="Fetch Zillow detail pages for heating/cooling/sewer.")
@click.option("--headed", is_flag=True, help="Run browser in headed (visible) mode for debugging.")
@click.option("--filter-commute", is_flag=True, help="Hide listings that exceed the commute limit.")
@click.option(
    "--output", "-o", default=None,
    help="Output file stem (e.g. 'results' → results.csv + results.json).",
)
def search(new, no_commute, enrich, headed, filter_commute, output):
    """Scrape listings, calculate commutes, and export to CSV + JSON.

    After export, run  /analyze-listings  in Claude Code to get AI notes
    on each property using your existing Claude subscription.
    """
    from config import get_params
    from output.exporter import export_both

    params = get_params(force_new=new)

    console.print(
        f"\n[bold]Searching:[/bold] {params.location}  |  "
        f"[bold]Budget:[/bold] "
        f"${params.min_price or 0:,} – "
        f"{'$' + f'{params.max_price:,}' if params.max_price else '∞'}  |  "
        f"[bold]Beds:[/bold] {params.min_beds}+  "
        f"[bold]Baths:[/bold] {params.min_baths}+\n"
        f"[dim]Sources: {', '.join(params.sources)}[/dim]\n"
    )

    listings = _run_search(params, no_commute=no_commute, enrich=enrich, headed=headed)

    if not listings:
        console.print("[yellow]No listings found. Try broadening your search parameters.[/yellow]")
        sys.exit(0)

    if filter_commute and not no_commute:
        before = len(listings)
        listings = [l for l in listings if l.within_commute_limit is not False]
        removed = before - len(listings)
        if removed:
            console.print(
                f"[dim]Removed {removed} listings exceeding the "
                f"{params.max_commute_minutes}-min commute limit.[/dim]"
            )

    _print_table(listings, params.max_commute_minutes)

    stem = output or f"hhunter_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    csv_path, json_path = export_both(listings, stem)
    console.print(f"\n[bold green]Exported:[/bold green]")
    console.print(f"  CSV  → [cyan]{csv_path}[/cyan]")
    console.print(f"  JSON → [cyan]{json_path}[/cyan]")
    console.print(
        f"\n[bold yellow]Next step:[/bold yellow] run [bold]/analyze-listings[/bold] "
        f"in Claude Code to get AI notes on each listing."
    )


@cli.command()
def setup():
    """Re-run the search preferences questionnaire."""
    from config import questionnaire
    questionnaire()


@cli.command()
def web():
    """Launch the basic web UI (Flask dev server on port 5000)."""
    from web.app import create_app
    app = create_app()
    console.print("[bold]Starting hhunter web UI → [cyan]http://127.0.0.1:5000[/cyan][/bold]")
    app.run(debug=True, port=5000)


if __name__ == "__main__":
    cli()
