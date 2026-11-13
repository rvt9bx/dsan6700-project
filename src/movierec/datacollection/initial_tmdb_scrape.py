# import packages
import logging
import time

import pandas as pd

from movierec.config import settings
from movierec.datacollection.tmdb import get_movie_info

logger = logging.getLogger(__name__)


def scrape_tmdb_movies(limit: int | None = None) -> None:
    """Scrape TMDB movie info for movies in the IMDB dataset."""
    # Verify API key status
    logger.info("API Key found" if settings.tmdb_api_key else "No API key found")

    # Read in movies dataset
    movies_df = pd.read_csv(settings.project_root / "data/clean/imdb_movies.csv")
    if limit:
        movies_df = movies_df.head(limit)
    results = []

    for _, row in movies_df.iterrows():
        title = row["primaryTitle"]
        tconst = row["tconst"]
        year = row["startYear"]
        logger.info(f"Getting data for {title}")

        movie_info = get_movie_info(title, year)

        # Check imdb id match
        imdb_id = movie_info.get("imdb_id")
        if tconst != imdb_id:
            pass

        results.append(
            {
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
        )

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
    cleaned_df.to_parquet(
        settings.project_root / "data/clean/tmdb_movies.parquet", index=False
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    scrape_tmdb_movies()
