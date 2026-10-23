# Data Collection

## Application

### IMDB Data

IMDB Data was downloaded on October 18th, 2026 from [IMDB Data](https://datasets.imdbws.com/). Additional information about this data can be found at the [Non-Commercial Dataset Documentation](https://data.imdb.com/non-commercial-datasets/).

The files downloaded for this project were title.akas.tsv.gz, title.basics.tsv.gz, and title.ratings.tsv.gz. These files are gzipped, tab-separated-values (TSV) formatted file in the UTF-8 character set. The title.basics data contains many columns, but the ones relevant to this project are the movie identifier, the type of movie, the title of the movie, the year each movie was released. The title.ratings data contains the average IMDB rating for each movie and the number of votes for each movie, as given by IMDB users. To replicate, download and save to data/imdb and extract to .tsv. 

**Script: `imdb_cleaning.py`**
This script processes the raw IMDB TSV files to produce a filtered movie dataset:
- Reads `title.basics.tsv` in chunks, filtering for movies (not TV shows, shorts, etc.), non-adult content, and release years ≥ 1930
- Reads `title.ratings.tsv` in chunks, joining only ratings for the filtered movie IDs
- Merges titles and ratings, drops entries without ratings/votes
- Filters to movies with ≥ 2000 votes
- Outputs `data/clean/imdb_movies.csv` with columns: tconst, titleType, primaryTitle, startYear, isAdult, averageRating, numVotes

Run with:
```bash
uv run src/movierec/datacollection/imdb_cleaning.py
```

### TMDB Data

The TMDB API was used in this project to query the TMDB database and acquire natural language overview data, as well as genre data. I queried the API by movie name and release year.

**Script: `initial_tmdb_scrape.py`**
This script enriches the filtered IMDB movie list with TMDB data:
- Reads `data/clean/imdb_movies.csv` produced by the IMDB cleaning script
- For each movie, queries the TMDB API via `get_movie_info(title, year)` to fetch TMDB ID, overview, and genres
- Includes a 0.25s rate-limiting delay between requests
- Outputs `data/clean/tmdb_movies.csv` with columns: tconst, tmdb_id, title, year, overview, genres
- Requires `TMDB_API_KEY` in environment (loaded via `movierec.config.settings`).

Run with:
```bash
uv run src/movierec/datacollection/initial_tmdb_scrape.py
```

## Evaluation

