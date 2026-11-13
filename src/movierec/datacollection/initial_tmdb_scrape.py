# import packages

import json
import logging
import time
from pathlib import Path

import pandas as pd
import requests

from movierec.config import settings
from movierec.datacollection.tmdb import get_movie_info

logger = logging.getLogger(__name__)


def _load_checkpoint(checkpoint_path: Path) -> list[dict]:
    """Load previously scraped records from a JSONL checkpoint file."""
    if not checkpoint_path.exists():
        return []
    with open(checkpoint_path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def scrape_tmdb_movies(limit: int | None = None) -> None:
    """Scrape TMDB movie info for movies in the IMDB dataset."""
    # Verify API key status
    logger.info("API Key found" if settings.tmdb_api_key else "No API key found")

    clean_dir = settings.project_root / "data/clean"
    checkpoint_path = clean_dir / "tmdb_scrape_checkpoint.jsonl"

    movies_df = pd.read_csv(clean_dir / "imdb_movies.csv")

    results = _load_checkpoint(checkpoint_path)
    scraped_ids = {r["tconst"] for r in results}
    if scraped_ids:
        logger.info(
            "Resuming from checkpoint (%d movies already scraped)", len(scraped_ids)
        )

    movies_df = movies_df[~movies_df["tconst"].isin(scraped_ids)]
    if limit is not None:
        movies_df = movies_df.head(limit)

    with open(checkpoint_path, "a", encoding="utf-8") as ckpt_file:
        for _, row in movies_df.iterrows():
            title = row["primaryTitle"]
            tconst = row["tconst"]
            year = row["startYear"]
            logger.info("Getting data for %s (%s)", title, year)

            try:
                movie_info = get_movie_info(title, year)
            except (requests.exceptions.RequestException, json.JSONDecodeError) as e:
                logger.error("Failed to fetch %s (%s): %s", title, tconst, e)
                continue

            record = {
                "tconst": tconst,
                "tmdb_id": movie_info.get("id"),
                "title": title,
                "year": year,
                "overview": movie_info.get("overview"),
                "genres": movie_info.get("genres"),
                "popularity": movie_info.get("popularity"),
                "poster_path": movie_info.get("poster_path"),
                "runtime": movie_info.get("runtime"),
            }
            results.append(record)
            ckpt_file.write(json.dumps(record) + "\n")
            ckpt_file.flush()

        # Rate limiting pause
        time.sleep(0.1)

    logger.info("Done!")

    # Convert to DataFrame
    tmdb_df = pd.DataFrame(results)

    # Clean dataframe for missing tmdb info
    mask = (
        tmdb_df["tmdb_id"].notna()
        & (tmdb_df["tmdb_id"] != "")
        & tmdb_df["overview"].notna()
        & (tmdb_df["overview"] != "")
        & tmdb_df["genres"].notna()
        & tmdb_df["genres"].map(bool)
    )
    cleaned_df = tmdb_df[mask].copy()

    # Convert id and year to int
    cleaned_df["tmdb_id"] = cleaned_df["tmdb_id"].astype(int)
    cleaned_df["year"] = cleaned_df["year"].astype(int)

    # Get genres as list of strings
    cleaned_df["genres"] = cleaned_df["genres"].apply(lambda x: [d["name"] for d in x])
    logger.info(f"Cleaned DataFrame head:\n{cleaned_df.head(2).to_string()}")

    # Save dataset
    cleaned_df.to_parquet(clean_dir / "tmdb_movies.parquet", index=False)
    checkpoint_path.unlink(missing_ok=True)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    scrape_tmdb_movies()
