"""Build a retrieval evaluation set (JSONL) from the MovieLens Tag Genome 2021 dataset.

Each line looks like:
    {"query": "Recommend me a time travel movie.",
     "relevant_ids": [105, 165, ...],          # TMDB ids (what Qdrant stores)
     "relevant_scores": [0.97, 0.95, ...],     # tag-genome scores, aligned with ids
     "tags": ["time travel"], "kind": "single"}

compare_retrieval.py only reads "query" and "relevant_ids"; the rest is metadata.

How it works
  1. Load your movies file -> the set of TMDB ids that are
     actually searchable in Qdrant.
  2. Map Tag Genome item_ids (MovieLens ids) -> TMDB ids, via MovieLens links.csv
  3. Load tag-genome scores (tagdl.csv or glmer.csv), keep only mapped movies.
  4. Single-tag queries: relevant = top-N movies scoring >= --min-score for that tag.
     Multi-tag queries: relevant = top-N movies scoring >= --min-score on ALL tags.
  5. Turn tags into natural-language queries with templates.
  6. Human checking and deleting queries that don't make sense (noun vs adjective)

Usage
    python build_eval_set.py

    python build_eval_set.py --list-tags        # review the tag vocabulary first
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

from movierec.config import settings
from movierec.retrieval.data import iter_movies

logger = logging.getLogger("build_eval_set")

# --------------------------------------------------------------------------- tag filtering
# Tags that aren't descriptions of what a movie is about (awards, quality judgements, numbers)
EXCLUDE_PATTERNS = [
    r"^\d+$",
    r"\b\d+\b",
    r"imdb",
    r"criterion",
    r"feature",
    r"movie",
    r"oscar",
    r"golden palm",
    r"award",
    r"title",
    r"debut",
    r"plot",
    r"author",
    r"script",
    r"credits",
    r"afi",
    r"sequel",
    r"\b(good|great|perfect|bad|better|awesome|excellent|exceptional|interesting|boring|overrated|underrated|hillarious|hilarious|funny)",
    r"\b(amazing|masterpiece|pointless|stupid|dumb|lame|long|better than expected|predictable)",
]


def tag_allowed(tag: str, patterns: list[re.Pattern]) -> bool:
    t = tag.strip().lower()
    return len(t) >= 3 and not any(p.search(t) for p in patterns)


# --------------------------------------------------------------------------- id mapping
_YEAR_RE = re.compile(r"\s*\((\d{4})\)\s*$")
_ARTICLE_RE = re.compile(r"^(.*),\s*(The|A|An)$", re.IGNORECASE)


def title_key(title: str, year: int | None = None) -> tuple[str, int | None]:
    """Normalise 'Godfather, The (1972)' and 'The Godfather' to the same key."""
    title = (title or "").strip()
    m = _YEAR_RE.search(title)
    if m:
        year = year or int(m.group(1))
        title = title[: m.start()]
    m = _ARTICLE_RE.match(title.strip())
    if m:
        title = f"{m.group(2)} {m.group(1)}"
    title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", title.lower()), year


def build_item_to_tmdb(
    records,
    links_path: Path | None,
) -> dict[int, int]:
    """MovieLens item_id -> TMDB id, restricted to TMDB ids present in `records`."""
    tmdb_ids = {r.tmdb_id for r in records}
    mapping: dict[int, int] = {}

    if links_path:
        links = pd.read_csv(links_path, dtype={"movieId": "int64"})
        links = links.dropna(subset=["tmdbId"])
        for movie_id, tmdb_id in zip(links["movieId"], links["tmdbId"].astype("int64")):
            if int(tmdb_id) in tmdb_ids:
                mapping[int(movie_id)] = int(tmdb_id)
        logger.info("links.csv mapped %d movies", len(mapping))

    if not mapping:
        raise SystemExit(
            "Could not map any Tag Genome movies to your TMDB ids. Set LINKS_PATH."
        )
    return mapping


# --------------------------------------------------------------------------- scores
def load_score_matrix(
    scores_path: Path, item_to_tmdb: dict[int, int], chunksize: int = 2_000_000
) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Return (scores [movies x tags], tag names, tmdb id per row)."""
    keep = set(item_to_tmdb)
    parts = []
    for chunk in pd.read_csv(
        scores_path,
        chunksize=chunksize,
        dtype={"tag": "string", "item_id": "int64", "score": "float32"},
        keep_default_na=False,  # tags like "null"/"NA" are real tags, not missing values
    ):
        parts.append(chunk[chunk["item_id"].isin(keep)])
    df = pd.concat(parts, ignore_index=True)
    df["tmdb_id"] = df["item_id"].map(item_to_tmdb)
    # two MovieLens ids could map to the same TMDB id: keep the first
    df = df.drop_duplicates(subset=["tmdb_id", "tag"])
    wide = df.pivot(index="tmdb_id", columns="tag", values="score").fillna(-1.0)
    logger.info("score matrix: %d movies x %d tags", *wide.shape)
    return wide.to_numpy(dtype=np.float32), list(wide.columns), wide.index.to_numpy()


# --------------------------------------------------------------------------- query text
def _a(phrase: str) -> str:
    return ("an " if phrase[:1].lower() in "aeiou" else "a ") + phrase


SINGLE_TEMPLATES = [
    "Recommend me {a_tag} movie.",
    "I'm in the mood for {a_tag} movie.",
    "{a_tag} film to watch tonight.",
    "Something about {tag}",
    "A movie about {tag}",
    "{a_tag} movie worth watching",
]
MULTI_TEMPLATES = [
    "I want {a_t1} movie that's also {t2}.",
    "A film that's both {t1} and {t2}.",
    "Something {t1} and {t2}",
    "A movie about {t1} and {t2}",
    "Recommend something {t1} with a {t2} feel.",
    "{t1} and {t2} movies",
]


def make_query(tags: list[str], rng: random.Random) -> str:
    if len(tags) == 1:
        t = tags[0]
        return rng.choice(SINGLE_TEMPLATES).format(tag=t, a_tag=_a(t))
    t1, t2 = tags
    return rng.choice(MULTI_TEMPLATES).format(t1=t1, t2=t2, a_t1=_a(t1))


# --------------------------------------------------------------------------- generation
def generate(
    S: np.ndarray,
    tags: list[str],
    tmdb_ids: np.ndarray,
    allowed: list[int],
    n_single: int,
    n_multi: int,
    min_score: float,
    min_relevant: int,
    max_relevant: int,
    rng: random.Random,
) -> list[dict]:
    high = S >= min_score  # movies x tags boolean

    def top_ids(
        mask: np.ndarray, rank_scores: np.ndarray
    ) -> tuple[list[int], list[float]]:
        idx = np.where(mask)[0]
        idx = idx[np.argsort(-rank_scores[idx])][:max_relevant]
        return [int(tmdb_ids[i]) for i in idx], [
            round(float(rank_scores[i]), 4) for i in idx
        ]

    usable = [j for j in allowed if high[:, j].sum() >= min_relevant]
    logger.info(
        "%d / %d tags are usable (>= %d movies at score >= %.2f)",
        len(usable),
        len(tags),
        min_relevant,
        min_score,
    )

    items: list[dict] = []
    seen: set[tuple[int, ...]] = set()

    # single-tag queries
    for j in rng.sample(usable, min(n_single, len(usable))):
        ids, scs = top_ids(high[:, j], S[:, j])
        items.append(
            {
                "tags": [tags[j]],
                "kind": "single",
                "relevant_ids": ids,
                "relevant_scores": scs,
            }
        )
        seen.add((j,))

    # multi-tag queries (random pairs with enough joint matches, not near-synonyms)
    attempts = 0
    n_made = 0
    while n_made < n_multi and attempts < n_multi * 200 and len(usable) >= 2:
        attempts += 1
        i, j = sorted(rng.sample(usable, 2))
        if (i, j) in seen:
            continue
        both = high[:, i] & high[:, j]
        either = high[:, i] | high[:, j]
        if both.sum() < min_relevant or both.sum() / either.sum() > 0.7:
            continue
        ids, scs = top_ids(both, np.minimum(S[:, i], S[:, j]))
        items.append(
            {
                "tags": [tags[i], tags[j]],
                "kind": "multi",
                "relevant_ids": ids,
                "relevant_scores": scs,
            }
        )
        seen.add((i, j))
        n_made += 1
    if n_made < n_multi:
        logger.warning("only built %d / %d multi-tag queries", n_made, n_multi)

    for item in items:
        item["query"] = make_query(item["tags"], rng)
    return items


# --------------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Tag Genome -> retrieval eval set (JSONL)")
    p.add_argument("--n-single", type=int, default=250)
    p.add_argument("--n-multi", type=int, default=200)
    p.add_argument(
        "--min-score",
        type=float,
        default=0.7,
        help="tag score a movie needs to count as relevant (scores are ~0-1)",
    )
    p.add_argument("--min-relevant", type=int, default=10)
    p.add_argument("--max-relevant", type=int, default=30)
    p.add_argument(
        "--list-tags", action="store_true", help="print usable tags and exit"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rng = random.Random(42)

    movies_path = Path(settings.movies_path)
    tags_path = Path(settings.tags_path)
    links_path = Path(settings.links_path)
    output_path = Path(settings.eval_path)

    if not tags_path.exists():
        raise SystemExit(f"Tag Genome scores file not found: {tags_path}")
    if not links_path.exists():
        raise SystemExit("links file not found (%s)", links_path)

    records = list(iter_movies(movies_path))
    logger.info("%d searchable movies (title + overview present)", len(records))

    item_to_tmdb = build_item_to_tmdb(records, links_path)
    logger.info("%d Tag Genome movies map onto your collection", len(item_to_tmdb))

    S, tags, tmdb_ids = load_score_matrix(tags_path, item_to_tmdb)

    # decide which tags may be used
    pats = [re.compile(p) for p in EXCLUDE_PATTERNS]
    allowed = [j for j, t in enumerate(tags) if tag_allowed(t, pats)]
    logger.info("%d / %d tags pass the filters", len(allowed), len(tags))

    if args.list_tags:
        high = (S >= args.min_score).sum(axis=0)
        for j in sorted(allowed, key=lambda j: tags[j]):
            print(f"{tags[j]}\t{int(high[j])}")
        return 0

    items = generate(
        S,
        tags,
        tmdb_ids,
        allowed,
        args.n_single,
        args.n_multi,
        args.min_score,
        args.min_relevant,
        args.max_relevant,
        rng,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")
    sizes = [len(i["relevant_ids"]) for i in items]
    logger.info(
        "wrote %d queries to %s (relevant per query: min %d, median %d, max %d)",
        len(items),
        output_path,
        min(sizes),
        int(np.median(sizes)),
        max(sizes),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
