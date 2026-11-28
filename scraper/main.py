"""CLI entry point for the Indian Box Office Data Engine."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Ensure scraper package modules resolve whether launched from root, /scraper, or /api
_SCRAPER_ROOT = Path(__file__).resolve().parent
if str(_SCRAPER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRAPER_ROOT))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config.settings import ConfigurationError, Settings, get_settings, load_sources_config
from database.supabase_sync import SupabaseSync
from enrichment.tmdb_client import TMDBClient
from scrapers.koimoi_scraper import KoimoiScraper
from scrapers.sacnilk_scraper import SacnilkScraper
from scrapers.tracker_aggregator import TrackerAggregator
from scrapers.x_tracker_scraper import XTrackerScraper
from utils.logger import RunReport, get_logger, setup_logging, write_run_report
from utils.models import MovieBoxOfficeRecord, RawScrapedMovie

LANGUAGE_CHOICES = (
    "all",
    "malayalam",
    "tamil",
    "hindi",
    "telugu",
    "kannada",
    "pan-india",
)

SOURCE_CHOICES = ("all", "sacnilk", "koimoi", "x")


def _normalize_language_arg(lang: str) -> str:
    mapping = {
        "all": "all",
        "malayalam": "Malayalam",
        "tamil": "Tamil",
        "hindi": "Hindi",
        "telugu": "Telugu",
        "kannada": "Kannada",
        "pan-india": "Pan-India",
    }
    return mapping[lang.lower()]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cinetracker",
        description="Fault-tolerant multi-source Indian Box Office Data Engine.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run full scrape, reconciliation, and TMDB enrichment without writing to Supabase.",
    )
    parser.add_argument(
        "--source",
        type=str.lower,
        default="all",
        choices=SOURCE_CHOICES,
        help="Run a specific scraper ('sacnilk', 'koimoi', or 'x') or 'all' (default).",
    )
    parser.add_argument(
        "--lang",
        type=str.lower,
        default="all",
        choices=LANGUAGE_CHOICES,
        help="Filter scraping by language category (default: all).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional cap on candidate movies processed per source.",
    )
    parser.add_argument(
        "--no-tmdb",
        action="store_true",
        help="Skip TMDB API metadata enrichment step.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to export reconciled records conforming to strict JSON contract.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose DEBUG console logging.",
    )
    return parser


def _render_rich_summary(
    records: list[MovieBoxOfficeRecord],
    *,
    report: RunReport,
    dry_run: bool,
) -> None:
    console = Console(width=165)

    table = Table(
        title="Indian Box Office Data Engine - Run Summary",
        show_lines=False,
        header_style="bold cyan",
    )
    table.add_column("Slug", style="dim", max_width=24, no_wrap=True)
    table.add_column("Title", style="bold white", max_width=28, no_wrap=True)
    table.add_column("Lang", style="magenta", no_wrap=True)
    table.add_column("Net (Cr)", justify="right", style="green", no_wrap=True)
    table.add_column("WW (Cr)", justify="right", style="bright_green", no_wrap=True)
    table.add_column("Budget (Cr)", justify="right", style="yellow", no_wrap=True)
    table.add_column("Verdict", style="cyan", max_width=20, no_wrap=True)
    table.add_column("Days", justify="right", no_wrap=True)
    table.add_column("TMDB", justify="right", no_wrap=True)
    table.add_column("Source", style="blue", no_wrap=True)
    table.add_column("Var>25%", justify="center", no_wrap=True)

    sorted_records = sorted(records, key=lambda r: r.india_net_cr, reverse=True)
    for rec in sorted_records[:40]:
        table.add_row(
            rec.movie_slug,
            rec.title,
            rec.language,
            f"₹{rec.india_net_cr:,.2f}",
            f"₹{rec.worldwide_gross_cr:,.2f}" if rec.worldwide_gross_cr is not None else "—",
            f"₹{rec.budget_cr:,.2f}" if rec.budget_cr is not None else "—",
            rec.verdict or "—",
            str(rec.day_count),
            str(rec.tmdb_id) if rec.tmdb_id else "—",
            rec.primary_source if len(rec.source_urls) <= 1 else f"{rec.primary_source}+",
            "[bold red]FLAG[/bold red]" if rec.variance_flag else "OK",
        )

    console.print()
    console.print(table)
    if len(sorted_records) > 40:
        console.print(f"[dim]... showing top 40 of {len(sorted_records)} movies[/dim]")

    mode_badge = "[yellow]DRY-RUN (No Supabase Write)[/yellow]" if dry_run else "[green]LIVE SYNC[/green]"
    summary_lines = (
        f"Mode: {mode_badge}  |  Status: [bold]{report.status.upper()}[/bold]  |  "
        f"Duration: {report.duration_sec:.2f}s\n"
        f"Reconciled Movies: {report.reconciliation.get('total_movies', 0)}  |  "
        f"Multi-Source Matches: {report.reconciliation.get('multi_source_matches', 0)}  |  "
        f"Variance Anomalies (>25%): {report.reconciliation.get('variance_anomalies', 0)}\n"
        f"TMDB Matched: {report.enrichment.get('tmdb_matched', 0)}  |  "
        f"Cache Hits: {report.enrichment.get('tmdb_cache_hits', 0)}  |  "
        f"DB Upserted: {report.database.get('upserted', 0)}  |  "
        f"Override Locked: {report.database.get('manual_override_locked', 0)}  |  "
        f"Errors: {len(report.errors)}"
    )
    console.print(Panel(summary_lines, title="Pipeline Telemetry", border_style="bright_blue"))


def run_pipeline(args: argparse.Namespace, *, settings: Settings | None = None) -> int:
    """Execute scrape -> reconcile -> enrich -> sync pipeline and return process exit code."""
    settings = settings or get_settings()
    settings.ensure_runtime_directories()
    setup_logging(
        log_file=settings.log_file_path,
        level="DEBUG" if args.verbose else settings.log_level,
    )
    logger = get_logger("main")

    normalized_lang = _normalize_language_arg(args.lang)
    report = RunReport(
        cli_args={
            "dry_run": args.dry_run,
            "source": args.source,
            "lang": normalized_lang,
            "limit": args.limit,
            "no_tmdb": args.no_tmdb,
        }
    )
    reconciled: list[MovieBoxOfficeRecord] = []

    try:
        if not args.dry_run:
            settings.validate_environment(require_supabase=True, require_tmdb=False)

        sources_cfg = load_sources_config(settings.sources_config_path)
        scraper_registry = {
            "sacnilk": SacnilkScraper,
            "koimoi": KoimoiScraper,
            "x": XTrackerScraper,
        }
        selected_sources = (
            ["sacnilk", "koimoi", "x"] if args.source == "all" else [args.source]
        )

        # Keep TrackerAggregator priority weights aligned with sources.yaml
        weights = dict(settings.source_weights)
        for s_name, s_cfg in sources_cfg.sources.items():
            weights[s_name] = s_cfg.priority_weight
        weights["x"] = sources_cfg.x_trackers.priority_weight

        raw_records: list[RawScrapedMovie] = []
        for src_name in selected_sources:
            if src_name == "x":
                if not sources_cfg.x_trackers.enabled:
                    logger.info("Skipping disabled source 'x'.")
                    continue
                try:
                    with XTrackerScraper(
                        settings=settings,
                        x_config=sources_cfg.x_trackers,
                    ) as scraper:
                        recs, metrics, err_events = scraper.scrape(
                            language=normalized_lang,
                            limit=args.limit,
                        )
                        raw_records.extend(recs)
                        report.sources[src_name] = metrics
                        for ev in err_events:
                            report.add_error(**ev)
                except Exception as exc:
                    logger.exception("Scraper 'x' aborted unexpectedly: %s", exc)
                    report.add_error(
                        stage="scraper_execution",
                        source="x",
                        exception_type=type(exc).__name__,
                        message=str(exc),
                    )
                continue

            src_cfg = sources_cfg.sources.get(src_name)
            if not src_cfg or not src_cfg.enabled:
                logger.info("Skipping disabled or unconfigured source '%s'.", src_name)
                continue

            scraper_cls = scraper_registry[src_name]
            try:
                with scraper_cls(settings=settings, source_config=src_cfg) as scraper:
                    recs, metrics, err_events = scraper.scrape(
                        language=normalized_lang,
                        limit=args.limit,
                    )
                    raw_records.extend(recs)
                    report.sources[src_name] = metrics
                    for ev in err_events:
                        report.add_error(**ev)
            except Exception as exc:
                logger.exception("Scraper '%s' aborted unexpectedly: %s", src_name, exc)
                report.add_error(
                    stage="scraper_execution",
                    source=src_name,
                    exception_type=type(exc).__name__,
                    message=str(exc),
                )

        aggregator = TrackerAggregator(settings=settings, source_weights=weights)
        reconciled, recon_summary = aggregator.reconcile(raw_records)
        report.reconciliation = recon_summary

        if not args.no_tmdb and reconciled:
            with TMDBClient(settings=settings) as tmdb:
                reconciled, tmdb_stats = tmdb.enrich_records(reconciled)
                report.enrichment = tmdb_stats

        if args.json_out:
            args.json_out.parent.mkdir(parents=True, exist_ok=True)
            payload = [rec.to_contract_dict() for rec in reconciled]
            args.json_out.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Wrote %d contract records to %s", len(payload), args.json_out)

        if args.dry_run:
            report.database["skipped_dry_run"] = len(reconciled)
            logger.info("Dry-run active: skipping Supabase write (%d records).", len(reconciled))
        else:
            sync_engine = SupabaseSync(settings=settings)
            sync_stats = sync_engine.sync_records(reconciled)
            report.database["upserted"] = sync_stats.upserted
            report.database["manual_override_locked"] = sync_stats.manual_override_locked
            report.database["daily_rows_synced"] = sync_stats.daily_rows_synced
            report.database["errors"] = sync_stats.errors

        # Mark failed if no movies were produced at all when errors occurred
        if not reconciled and report.errors:
            report.finalize(status="failed")
        else:
            report.finalize()

    except ConfigurationError as cfg_err:
        logger.error("Configuration error: %s", cfg_err)
        report.add_error(
            stage="configuration",
            exception_type=type(cfg_err).__name__,
            message=str(cfg_err),
        )
        report.finalize(status="failed")
    except Exception as exc:
        logger.exception("Fatal pipeline failure: %s", exc)
        report.add_error(
            stage="pipeline",
            exception_type=type(exc).__name__,
            message=str(exc),
        )
        report.finalize(status="failed")
    finally:
        write_run_report(report, settings.report_file_path)
        logger.info("Saved run report to %s", settings.report_file_path)

    _render_rich_summary(reconciled, report=report, dry_run=args.dry_run)
    return 1 if report.status == "failed" else 0


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return run_pipeline(args)


if __name__ == "__main__":
    sys.exit(main())
