# Data Collection

## Application

The data collection pipeline is orchestrated by `src/movierec/datacollection/pipeline.py` and exposed via the `movierec-collect` CLI entrypoint. Running the pipeline executes three sequential steps: downloading raw IMDb datasets (`imdb_download.py`), filtering and merging the IMDb tables (`imdb_cleaning.py`), and enriching the resulting movie list with metadata from the TMDB API (`initial_tmdb_scrape.py`).

### Running the Pipeline

Run the full end-to-end collection pipeline using the registered script entrypoint:

```bash
uv run movierec-collect
```

You can also skip individual stages or restrict the TMDB scrape to a smaller sample during development:

```bash
# Reuse existing IMDb files and scrape only the first 100 movies
uv run movierec-collect --skip-download --skip-clean --limit 100
```

---

### IMDb Data

IMDb data was originally downloaded on October 18th, 2026 from [IMDb Data](https://datasets.imdbws.com/). Additional information about this data can be found at the [Non-Commercial Dataset Documentation](https://data.imdb.com/non-commercial-datasets/).

The pipeline uses `title.basics.tsv.gz` and `title.ratings.tsv.gz`, which are gzipped, UTF-8 encoded tab-separated-values (TSV) archives. `title.basics` supplies the movie identifier (`tconst`), title type (`titleType`), primary title (`primaryTitle`), release year (`startYear`), and adult-content flag (`isAdult`), while `title.ratings` supplies the average user rating (`averageRating`) and vote count (`numVotes`).

**Step 1: Download & Extract (`imdb_download.py`)**
- Downloads `title.basics.tsv.gz` and `title.ratings.tsv.gz` from `https://datasets.imdbws.com/` into `data/imdb/`
- Decompresses each `.gz` archive into a `.tsv` file and deletes the compressed archive to save disk space
- Can be run standalone via:
  ```bash
  uv run src/movierec/datacollection/imdb_download.py
  ```

**Step 2: Clean & Merge (`imdb_cleaning.py`)**
- Reads `data/imdb/title.basics.tsv` in chunks of 10,000 rows, filtering for feature movies (`titleType == "movie"`), non-adult titles (`isAdult == "0"`), and release years ≥ 1930
- Reads `data/imdb/title.ratings.tsv` in chunks of 10,000 rows and keeps ratings matching the filtered movie IDs
- Merges the title and rating datasets on `tconst`, drops rows without ratings or votes, and retains movies with at least 2,000 votes (`numVotes >= 2000`)
- Outputs `data/clean/imdb_movies.csv` with columns: `tconst`, `titleType`, `primaryTitle`, `startYear`, `isAdult`, `averageRating`, and `numVotes`
- Can be run standalone via:
  ```bash
  uv run src/movierec/datacollection/imdb_cleaning.py
  ```

---

### TMDB Data

The TMDB API was used to query the TMDB database by movie title and release year to acquire natural-language plot overviews, genres, popularity metrics, poster paths, and runtimes.

**Step 3: Scrape & Enrich (`initial_tmdb_scrape.py`)**
- Requires `TMDB_API_KEY` in the environment (loaded via `movierec.config.settings`)
- Reads `data/clean/imdb_movies.csv` and queries the TMDB API for each movie via `get_movie_info(title, year)` with a 0.25-second rate-limiting delay between requests
- Filters out movies missing a `tmdb_id`, `overview`, or non-empty `genres` list, and extracts genre names into a clean list of strings
- Outputs `data/clean/tmdb_movies.parquet` with columns: `tconst`, `tmdb_id`, `title`, `year`, `overview`, `genres`, `popularity`, `poster_path`, and `runtime`
- Can be run standalone via:
  ```bash
  uv run src/movierec/datacollection/initial_tmdb_scrape.py
  ```
