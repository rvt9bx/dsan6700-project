"""Download the IMDb title and ratings datasets."""

import gzip
import shutil

import requests
from loguru import logger

from movierec.config import settings
from movierec.logging_setup import configure_logging

# Define the IMDb datasets to download
DATASETS = [
    "title.basics.tsv.gz",
    "title.ratings.tsv.gz",
]


def download_imdb_datasets() -> None:
    """Downloads and decompresses official IMDb datasets into data/imdb/ relative to project_root."""
    # Build output path
    output_dir = settings.project_root / "data" / "imdb"
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.bind(output_dir=str(output_dir)).info("Ensuring output directory exists")

    for filename in DATASETS:
        url = f"https://datasets.imdbws.com/{filename}"
        gz_path = output_dir / filename
        tsv_path = output_dir / filename.replace(".gz", "")

        log = logger.bind(file=filename)
        log.info("Starting download")
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()

            # Save the compressed .gz file
            with open(gz_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            log.info("Downloaded archive")

            # Decompress into a readable .tsv file
            log.info("Decompressing")
            with gzip.open(gz_path, "rb") as f_in, open(tsv_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

            # Clean up the .gz archive to save disk space
            gz_path.unlink()
            log.bind(saved_to=str(tsv_path)).info("Processed and saved")

        except requests.exceptions.RequestException as e:
            log.bind(error=str(e)).error("Network/HTTP error while downloading")
            raise
        except Exception as e:
            log.bind(error=str(e)).error("Unexpected error while processing")
            raise

    logger.info("All IMDb dataset tasks finished.")


if __name__ == "__main__":
    configure_logging(log_file=False)
    download_imdb_datasets()
