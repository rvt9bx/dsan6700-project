# Evaluation
 
## Application
 
The evaluation module measures how well vector search retrieves movies, using a BM25 keyword search over the same movie overviews as a baseline. Ground truth comes from the [MovieLens](https://grouplens.org/datasets/movielens/) Tag Genome, which scores how strongly each movie expresses tags such as "time travel" or "dark comedy". The module lives in `src/movierec/evaluation/` and runs as three sequential steps: downloading the MovieLens files (`download_eval_data.py`), turning tags into queries with labeled relevant movies (`build_eval_set.py`), and comparing the two retrieval methods on those queries (`compare_retrieval.py`). The BM25 retriever itself is in `src/movierec/retrieval/bm25.py`.
 
### Prerequisites
 
- The movies are ingested into Qdrant (`movierec-collect`, then `movierec-ingest`), so there is a collection to search and `data/clean/tmdb_movies.parquet` exists.
- Qdrant is reachable. If you use the on-disk local mode, only one process can open the folder at a time, so stop the API and ingest job first.

### Running the Evaluation
 
```bash
# 1. Download the MovieLens files into data/eval/
uv run movierec-eval-download
 
# 2. Review the available tags, then build the eval set
uv run movierec-eval-build --list-tags
uv run movierec-eval-build 

# 3. Human checks, outside code
 
# 4. Compare vector search against BM25
uv run movierec-eval-compare --k 5 10 20 
```

---
 
### MovieLens Data
 
The data lives in `data/eval/` and is **not committed**: MovieLens does not permit public redistribution, so each person downloads it from GroupLens. Paths are set in `movierec.config.settings` and can be overridden in `.env`.
 
| File | Source | Setting | Purpose |
| --- | --- | --- | --- |
| `tagdl.csv` | `genome_2021.zip` (Tag Genome 2021: about 10.5M scores, 1,084 tags, 9,734 movies) | `TAGS_PATH` | Tag relevance scores (`tag`, `item_id`, `score`) |
| `links.csv` | `ml-latest.zip` | `LINKS_PATH` | Maps MovieLens ids to TMDB ids (`movieId`, `imdbId`, `tmdbId`) |
 
**Step 1: Download (`download_eval_data.py`)**
- Downloads `genome_2021.zip` (about 1.8 GB) and `ml-latest.zip` from `files.grouplens.org`, extracts only `tagdl.csv` and `links.csv` into `data/eval/`, and deletes the archives
- Needs roughly the archive size in free disk space while it runs, because each zip is downloaded to a temporary folder first
- Skips files that already exist; `--force` downloads them again
- `--genome-url` and `--links-url` point at different archives, for example `--links-url https://files.grouplens.org/datasets/movielens/ml-32m.zip` for a newer `links.csv`
 
---
 
### Building the Eval Set
 
**Step 2: Build Queries (`build_eval_set.py`)**
- Reads `data/clean/tmdb_movies.parquet` through the same cleaning as ingestion, so every relevant movie is one that exists in the index
- Maps Tag Genome ids to TMDB ids using `links.csv`, falling back to a normalized title and year match from `metadata.json`
- Drops tags that don't describe content (awards, formats, quality judgments like "good"); `--list-tags` shows what remains, and `--exclude-tags-file` or `--allow-tags-file` adjust it
- **Single-tag queries:** relevant movies are those scoring at least `--min-score` (default 0.7) on the tag, capped at the top `--max-relevant` (default 30)
- **Two-tag queries:** a movie must clear the threshold on both tags and is ranked by its lower score; near-synonym pairs are skipped
- Tags with fewer than `--min-relevant` (default 10) matching movies are skipped
- Turns tags into natural-language queries with templates like "Recommend me a time travel movie."
- Outputs `data/eval/eval_queries.jsonl`, one query per line, with the fields `query`, `relevant_ids` (TMDB ids), `relevant_scores`, `tags` and `kind` (`single` or `multi`):
```json
{"query": "Recommend me a time travel movie.", "relevant_ids": [105, 165], "relevant_scores": [0.97, 0.95], "tags": ["time travel"], "kind": "single"}
```
- Useful options: `--n-single` (default 150), `--n-multi` (default 100), `--seed` (default 42, so the same inputs give the same eval set)
- The eval set queries were edited by a human (Ellie on 11/23/26) to reconcile adjectives/verbs/nouns and make the templated queries more like natural language. Some multi-tag rows were deleted because the two tags were almost the same word, and some "relevant" movies were deleted based on limited human relevance checks. 

---
 
### Comparing Retrieval Methods
 
**Step 3: Compare (`compare_retrieval.py`)**
- Runs every query through vector search (`Retriever.search_vectors`) and through BM25 (`BM25Retriever.search_many`), then scores both against `relevant_ids`
- BM25 indexes the `overview` text stored in the Qdrant payloads, so both methods search exactly the same movies
- Reports each metric overall and separately for single-tag and two-tag queries:
| Metric | Meaning |
| --- | --- |
| `P@k` | Share of the top k results that are relevant |
| `R@k` | Share of all relevant movies found in the top k |
| `nDCG@k` | Rewards relevant movies ranked higher |
| `MRR` | 1 / rank of the first relevant result |
 
- `--k` accepts several cutoffs, for example `--k 5 10 20`
- Warns if any relevant ids are missing from the Qdrant collection, since those can never be retrieved
 
### Reading the Results
 
- Tag Genome scores are model-predicted, so the ground truth is noisy.
- Each query has between 10 and 30 relevant movies, so P@20 cannot reach 1.0 for a query with only 10, and R@10 tops out near 0.33 for a query with 30. The ceilings are the same for both methods, so differences between them are meaningful even though the absolute numbers look low.
- Mood tags like "quirky" rarely appear in overview text, which disadvantages BM25. Short queries such as "heist movie" favor it. Comparing the `single` and `multi` tables helps separate these effects.

---
 
### Citation
 
- Kotkov, D., Maslov, A., and Neovius, M. (2021). Revisiting the tag relevance prediction problem.
- Vig, J., Sen, S., and Riedl, J. (2012). The Tag Genome: Encoding Community Knowledge to Support Novel Interaction. *ACM Trans. Interact. Intell. Syst.* 2, 3, Article 13. https://doi.org/10.1145/2362394.2362395
 