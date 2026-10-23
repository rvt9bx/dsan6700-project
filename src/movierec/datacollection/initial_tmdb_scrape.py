# import packages
import time

import pandas as pd

from movierec.config import settings
from movierec.datacollection.tmdb import get_movie_info


def scrape_tmdb_movies() -> None:
    """Scrape TMDB movie info for movies in the IMDB dataset."""
    # Verify API key status
    print("API Key found" if settings.tmdb_api_key else "No API key found")

    # Read in movies dataset
    movies_df = pd.read_csv("data/clean/imdb_movies.csv")

    results = []

    for _, row in movies_df.iterrows():
        title = row["primaryTitle"]
        tconst = row["tconst"]
        year = row["startYear"]
        print(f"Getting data for {title}")

        movie_info = get_movie_info(title, year)

        results.append(
            {
                "tconst": tconst,
                "tmdb_id": movie_info.get("id"),
                "title": title,
                "year": year,
                "overview": movie_info.get("overview"),
                "genres": movie_info.get("genres", []),
            }
        )

        # Rate limiting pause
        time.sleep(0.25)

    print("Done!")

    # Convert to DataFrame
    tmdb_df = pd.DataFrame(results)
    print(tmdb_df.head())

    # Save dataset
    tmdb_df.to_csv("data/clean/tmdb_movies.csv", index=False)


if __name__ == "__main__":
    scrape_tmdb_movies()
