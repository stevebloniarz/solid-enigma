#!/usr/bin/env python3
"""hhunter — CLI house hunting aggregator."""

import sys
from datetime import datetime
from pathlib import Path

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

load_dotenv()

console = Console()


def _run_search(params, ai: bool, no_commute: bool) -> list:
    from scrapers import SCRAPERS
    from analysis.price import assess_prices
    from analysis.ai_analysis import analyze_listings
    from commute.calculator import calculate_commutes

    all_listings = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        for source in params.sources:
            task = progress.add_task(f"Searching {source}...", total=None)
            try:
                scraper = SCRAPERS[source]()
                results = scraper.search(params)
                all_listings.extend(results)
                progress.update(task, description=f"[green]{source}: {len(results)} listings[/green]")
            except Exception as e:
                progress.update(task, description=f"[red]{source} failed: {e}[/red]")
            finally:
                progress.stop_task(task)

        if not all_listings:
            return []

        task = progress.add_task("Analyzing prices...", total=None)
        all_listings = assess_prices(all_listings)
        progress.stop_task(task)

        if not no_commute:
            task = progress.add_task("Calculating commute times (rush hour)...", total=None)
            all_listings = calculate_commutes(all_listings, params)
            progress.stop_task(task)

        if ai:
            task = progress.add_task("Running AI analysis (Claude)...", total=None)
            all_listings = analyze_listings(all_listings)
            progress.stop_task(task)

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
    table.add_column("Price", justify="center")  # assessment
    table.add_column("AM", justify="right")
    table.add_column("PM", justify="right")
    table.add_column("DOM", justify="right")
    table.add_column("URL", style="dim")

    for l in listings:
        price_str = f"${l.price:,.0f}" if l.price else "-"
        bed_bath = f"{l.beds or '-'}/{l.baths or '-'}/{l.sqft or '-'}"
        ppsf = f"${l.price_per_sqft:.0f}" if l.price_per_sqft else "-"

        pa = l.price_assessment or "-"
        if pa == "low":
            pa_str = f"[green]{pa}[/green]"
        elif pa == "high":
            pa_str = f"[red]{pa}[/red]"
        else:
            pa_str = pa

        am = f"{l.commute_minutes_am}m" if l.commute_minutes_am is not None else "-"
        pm = f"{l.commute_minutes_pm}m" if l.commute_minutes_pm is not None else "-"

        commute_over = (
            l.commute_minutes_am is not None
            and l.commute_minutes_pm is not None
            and max(l.commute_minutes_am, l.commute_minutes_pm) > max_commute
        )
        if commute_over:
            am = f"[red]{am}[/red]"
            pm = f"[red]{pm}[/red]"

        dom = str(l.days_on_market) if l.days_on_market is not None else "-"
        short_addr = f"{l.address}, {l.city}"
        url = l.url[:55] + "…" if len(l.url) > 56 else l.url

        table.add_row(
            l.source, short_addr, price_str, bed_bath, ppsf,
            pa_str, am, pm, dom, url,
        )

    console.print(table)


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx):
    if ctx.invoked_subcommand is None:
        ctx.invoke(search)


@cli.command()
@click.option("--new", is_flag=True, help="Ignore saved preferences and re-run setup.")
@click.option("--ai", is_flag=True, help="Run Claude AI analysis on each listing.")
@click.option("--no-commute", is_flag=True, help="Skip commute time calculation.")
@click.option(
    "--output", "-o", default=None,
    help="Output file stem (e.g. 'results' → results.csv + results.json). "
         "Defaults to timestamped filename.",
)
@click.option("--filter-commute", is_flag=True, help="Only show listings within commute limit.")
def search(new, ai, no_commute, output, filter_commute):
    """Search for listings and export to CSV + JSON."""
    from config import get_params
    from output.exporter import export_both

    params = get_params(force_new=new)

    console.print(
        f"\n[bold]Searching:[/bold] {params.location}  |  "
        f"[bold]Budget:[/bold] ${params.min_price or 0:,} – ${params.max_price or '∞':,}  |  "
        f"[bold]Beds:[/bold] {params.min_beds}+  [bold]Baths:[/bold] {params.min_baths}+\n"
    )

    listings = _run_search(params, ai=ai, no_commute=no_commute)

    if not listings:
        console.print("[yellow]No listings found. Try broadening your search parameters.[/yellow]")
        sys.exit(0)

    if filter_commute and not no_commute:
        before = len(listings)
        listings = [l for l in listings if l.within_commute_limit is not False]
        removed = before - len(listings)
        if removed:
            console.print(f"[dim]Filtered out {removed} listings exceeding {params.max_commute_minutes}-min commute.[/dim]")

    _print_table(listings, params.max_commute_minutes)

    stem = output or f"hhunter_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    csv_path, json_path = export_both(listings, stem)
    console.print(f"\n[bold green]Exported:[/bold green]")
    console.print(f"  CSV  → [cyan]{csv_path}[/cyan]")
    console.print(f"  JSON → [cyan]{json_path}[/cyan]")

    if any(l.notable_features for l in listings):
        console.print("\n[bold]Notable Features:[/bold]")
        for l in listings:
            if l.notable_features and "not set" not in (l.notable_features or ""):
                console.print(f"  [dim]{l.address}:[/dim] {l.notable_features}")


@cli.command()
def setup():
    """Re-run the search preferences questionnaire."""
    from config import questionnaire
    questionnaire()


@cli.command()
def web():
    """Launch the web UI (Flask dev server)."""
    from web.app import create_app
    app = create_app()
    console.print("[bold]Starting hhunter web UI at [cyan]http://127.0.0.1:5000[/cyan][/bold]")
    app.run(debug=True, port=5000)


if __name__ == "__main__":
    cli()
