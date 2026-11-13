"""movierec-collect: download IMDb datasets, filter movies, and enrich via TMDB."""

from __future__ import annotations

import argparse

from loguru import logger

from movierec.datacollection.imdb_cleaning import clean_imdb_data
from movierec.datacollection.imdb_download import download_imdb_datasets
from movierec.datacollection.initial_tmdb_scrape import scrape_tmdb_movies
from movierec.logging_setup import configure_logging


def run_collection(
    skip_download: bool = False,
    skip_clean: bool = False,
    skip_scrape: bool = False,
    limit: int | None = None,
) -> None:
    """Run the full data collection pipeline in sequence."""
    if not skip_download:
        logger.info("=== Step 1/3: Downloading IMDb datasets ===")
        download_imdb_datasets()

    if not skip_clean:
        logger.info("=== Step 2/3: Cleaning IMDb datasets ===")
        clean_imdb_data()

    if not skip_scrape:
        logger.info("=== Step 3/3: Scraping TMDB metadata ===")
        scrape_tmdb_movies(limit=limit)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="movierec-collect",
        description="Download IMDb datasets, clean titles, and enrich with TMDB metadata.",
    )
    p.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip downloading raw IMDb TSV files",
    )
    p.add_argument(
        "--skip-clean",
        action="store_true",
        help="Skip cleaning IMDb TSV files into imdb_movies.csv",
    )
    p.add_argument(
        "--skip-scrape",
        action="store_true",
        help="Skip scraping TMDB metadata",
    )
    p.add_argument(
        "--limit",
        type=int,
        help="Only scrape the first N cleaned IMDb movies (useful for testing)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(log_file=False)
    run_collection(
        skip_download=args.skip_download,
        skip_clean=args.skip_clean,
        skip_scrape=args.skip_scrape,
        limit=args.limit,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
