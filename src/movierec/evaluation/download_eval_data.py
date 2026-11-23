"""Download the MovieLens files the evaluation module needs and place them where settings expects.

    genome_2021.zip (~1.8 GB) -> tagdl.csv     -> settings.tags_path
    ml-latest.zip             -> links.csv     -> settings.links_path

Only those files are kept: each archive is downloaded to a temporary folder, the needed members
are extracted, and the archive is deleted. Files that already exist are skipped unless --force.

Usage:
    python download_eval_data.py
    python download_eval_data.py --force
    python download_eval_data.py --links-url https://files.grouplens.org/datasets/movielens/ml-32m.zip
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from loguru import logger

from movierec.config import settings

GENOME_URL = "https://files.grouplens.org/datasets/tag-genome-2021/genome_2021.zip"
LINKS_URL = "https://files.grouplens.org/datasets/movielens/ml-latest.zip"

CHUNK_BYTES = 1024 * 1024
LOG_EVERY_BYTES = 100 * CHUNK_BYTES
USER_AGENT = "movierec-eval-downloader"


def download(url: str, dest: Path) -> None:
    """Stream `url` to `dest`, logging progress."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request) as response, dest.open("wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = next_log = 0
        while chunk := response.read(CHUNK_BYTES):
            out.write(chunk)
            done += len(chunk)
            if done >= next_log:
                of_total = f" of {total / 1e6:,.0f} MB" if total else ""
                logger.info(" downloaded %s MB%s", f"{done / 1e6:,.0f}", of_total)
                next_log = done + LOG_EVERY_BYTES
    logger.info(" download complete (%s MB)", f"{done / 1e6:,.0f}")


def extract_member(zip_path: Path, filename: str, dest: Path) -> None:
    """Copy the one archive member called `filename` (any folder) to `dest`."""
    with zipfile.ZipFile(zip_path) as zf:
        matches = [n for n in zf.namelist() if Path(n).name == filename]
        if not matches:
            raise FileNotFoundError(f"{filename} not found in {zip_path.name}")
        if len(matches) > 1:
            raise RuntimeError(f"{filename} is ambiguous in {zip_path.name}: {matches}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        partial = dest.with_name(dest.name + ".part")
        with zf.open(matches[0]) as src, partial.open("wb") as out:
            shutil.copyfileobj(src, out, CHUNK_BYTES)
        partial.replace(dest)  # only appears once fully written
    logger.info("  extracted %s -> %s", matches[0], dest)


def fetch(url: str, targets: dict[str, Path], force: bool = False) -> None:
    """Download one archive and extract `targets` ({member filename: destination})."""
    todo = {name: dest for name, dest in targets.items() if force or not dest.exists()}
    if not todo:
        logger.info("Already present, skipping %s", url)
        return

    work_dir = next(iter(todo.values())).parent
    work_dir.mkdir(parents=True, exist_ok=True)
    # temp folder lives next to the data so the (large) archive stays on the same disk
    with tempfile.TemporaryDirectory(dir=work_dir, prefix=".download_") as tmp:
        archive = Path(tmp) / "archive.zip"
        logger.info("Downloading %s", url)
        download(url, archive)
        for name, dest in todo.items():
            extract_member(archive, name, dest)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Download the MovieLens evaluation data")
    p.add_argument(
        "--force", action="store_true", help="re-download even if files exist"
    )
    p.add_argument("--genome-url", default=GENOME_URL, help="Tag Genome 2021 zip")
    p.add_argument(
        "--links-url", default=LINKS_URL, help="MovieLens zip containing links.csv"
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    tags_path = Path(settings.tags_path)
    links_path = Path(settings.links_path)

    fetch(
        args.genome_url,
        {"tagdl.csv": tags_path},
        force=args.force,
    )
    fetch(args.links_url, {"links.csv": links_path}, force=args.force)
    logger.info("Done. Next: build_eval_set.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
