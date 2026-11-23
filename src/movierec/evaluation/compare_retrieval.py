"""Compare vector search against the BM25 baseline on an eval set built by build_eval_set.py.

Usage:
    python compare_retrieval.py                          # reads eval_queries.jsonl from settings
    python compare_retrieval.py data/eval/eval_queries.jsonl --k 5 10 20

Each line of the eval file is a JSON object with (extra fields are ignored):
    {"query": "...", "relevant_ids": [<tmdb ids>], "kind": "single" | "multi", ...}

Metrics (binary relevance, averaged over queries; reported overall and per `kind`):
    P@k     fraction of the top k that are relevant (always divided by k)
    R@k     fraction of the relevant movies found in the top k
    nDCG@k  rank-aware gain, 1.0 = every relevant movie ranked first
    MRR     1 / rank of the first relevant movie (searched down to max(k))

Results are written to a JSON file under <project_root>/data/eval/results/.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from movierec.config import settings
from movierec.retrieval import Retriever
from movierec.retrieval.bm25 import BM25Retriever


# --------------------------------------------------------------------------- metrics
def precision_at_k(ranked: Sequence[int], relevant: set[int], k: int) -> float:
    """Share of the top k results that are relevant (divides by k even if fewer returned)."""
    return sum(1 for i in ranked[:k] if i in relevant) / k


def recall_at_k(ranked: Sequence[int], relevant: set[int], k: int) -> float:
    """Share of all relevant movies that appear in the top k."""
    return sum(1 for i in ranked[:k] if i in relevant) / max(len(relevant), 1)


def ndcg_at_k(ranked: Sequence[int], relevant: set[int], k: int) -> float:
    """Binary-relevance nDCG: discounts hits by rank, normalised by the best possible order."""
    dcg = sum(
        1 / math.log2(i + 2) for i, doc in enumerate(ranked[:k]) if doc in relevant
    )
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / ideal if ideal else 0.0


def reciprocal_rank(ranked: Sequence[int], relevant: set[int]) -> float:
    """1 / rank of the first relevant result, 0 if none was returned."""
    for i, doc in enumerate(ranked):
        if doc in relevant:
            return 1 / (i + 1)
    return 0.0


def query_metrics(
    ranked: Sequence[int], relevant: set[int], ks: Sequence[int]
) -> dict[str, float]:
    """All metrics for one query."""
    out: dict[str, float] = {}
    for k in ks:
        out[f"P@{k}"] = precision_at_k(ranked, relevant, k)
        out[f"R@{k}"] = recall_at_k(ranked, relevant, k)
        out[f"nDCG@{k}"] = ndcg_at_k(ranked, relevant, k)
    out["MRR"] = reciprocal_rank(ranked, relevant)
    return out


# --------------------------------------------------------------------------- eval file
def load_eval_set(path: Path) -> list[dict]:
    """Read eval_queries.jsonl -> [{"query", "relevant" (set of tmdb ids), "kind"}]."""
    rows = []
    with path.open() as f:
        for line in f:
            obj = json.loads(line)
            rows.append(
                {
                    "query": obj["query"],
                    "relevant": set(obj["relevant_ids"]),
                    "kind": obj.get("kind", "unknown"),
                }
            )
    return rows


# --------------------------------------------------------------------------- reporting
def summarise(per_query: list[dict[str, float]], idx: list[int]) -> dict[str, float]:
    """Mean of each metric over the queries at positions `idx`."""
    keys = per_query[0].keys()
    return {key: sum(per_query[i][key] for i in idx) / len(idx) for key in keys}


def write_results(
    results: dict[str, dict[str, dict[str, float]]],
    groups: dict[str, list[int]],
    ks: list[int],
    eval_file: Path,
    output_dir: Path,
) -> Path:
    """Write evaluation results to a JSON file."""
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"eval_results_{timestamp}.json"

    # Build serializable output
    serializable_groups: dict[str, dict[str, object]] = {}
    for name, idx in groups.items():
        serializable_groups[name] = {
            "num_queries": len(idx),
            "methods": results[name],
        }
    serializable = {
        "timestamp": timestamp,
        "eval_file": str(eval_file),
        "cutoffs_k": ks,
        "groups": serializable_groups,
    }

    with output_file.open("w") as f:
        json.dump(serializable, f, indent=2)

    return output_file


# --------------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Vector search vs BM25 on an eval set")
    p.add_argument(
        "eval_file",
        type=Path,
        nargs="?",
        default=settings.eval_path,
        help=f"JSONL from build_eval_set.py (default: {settings.eval_path})",
    )
    p.add_argument(
        "--k",
        type=int,
        nargs="+",
        default=[10],
        help="cutoffs for P@k / R@k / nDCG@k, e.g. --k 5 10 20",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ks = sorted(set(args.k))
    max_k = ks[-1]

    rows = load_eval_set(args.eval_file)
    queries = [r["query"] for r in rows]
    print(f"{len(rows)} queries from {args.eval_file}")

    vec = Retriever.from_settings(settings)
    vec.warmup()
    bm25 = BM25Retriever.from_store(vec.store)

    # sanity check: relevant ids that aren't in Qdrant can never be retrieved
    all_relevant = sorted({i for r in rows for i in r["relevant"]})
    present = vec.store.existing_ids(all_relevant)
    if len(present) < len(all_relevant):
        print(
            f"warning: only {len(present)}/{len(all_relevant)} relevant ids exist in the "
            "Qdrant collection; recall is capped for both methods"
        )

    # each method -> one ranked list of tmdb ids per query
    rankings = {
        "vector": [
            [h.tmdb_id for h in hits]
            for hits in vec.search_vectors(vec.embed_queries(queries), limit=max_k)
        ],
        "bm25": [
            [h.tmdb_id for h in hits] for hits in bm25.search_many(queries, limit=max_k)
        ],
    }

    per_query = {
        method: [
            query_metrics(ranked, row["relevant"], ks)
            for ranked, row in zip(lists, rows)
        ]
        for method, lists in rankings.items()
    }

    groups: dict[str, list[int]] = {"all": list(range(len(rows)))}
    by_kind: dict[str, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        by_kind[row["kind"]].append(i)
    if len(by_kind) > 1:
        groups.update(sorted(by_kind.items()))

    # Compute summaries for each group
    summaries: dict[str, dict[str, dict[str, float]]] = {}
    for name, idx in groups.items():
        summaries[name] = {
            method: summarise(pq, idx) for method, pq in per_query.items()
        }
        # Print brief summary to console
        print(f"\n{name} ({len(idx)} queries, MRR over top {max_k})")
        for method, vals in summaries[name].items():
            metric_str = "  ".join(f"{m}={vals[m]:.3f}" for m in vals)
            print(f"  {method:<8} {metric_str}")

    # Write detailed results to file
    output_dir = settings.project_root / "data" / "eval" / "results"
    output_file = write_results(summaries, groups, ks, args.eval_file, output_dir)
    print(f"\nResults written to {output_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
