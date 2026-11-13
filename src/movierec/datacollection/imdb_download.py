import gzip
import logging
import shutil

import requests

from movierec.config import settings

# Set up module-level logger
logger = logging.getLogger(__name__)

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

    logger.info("Ensuring output directory exists at: %s", output_dir)

    for filename in DATASETS:
        url = f"https://datasets.imdbws.com/{filename}"
        gz_path = output_dir / filename
        tsv_path = output_dir / filename.replace(".gz", "")

        logger.info("Starting download for %s...", filename)
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()

            # Save the compressed .gz file
            with open(gz_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            logger.info("Successfully downloaded archive: %s", filename)

            # Decompress into a readable .tsv file
            logger.info("Decompressing %s...", filename)
            with gzip.open(gz_path, "rb") as f_in, open(tsv_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

            # Clean up the .gz archive to save disk space
            gz_path.unlink()
            logger.info("Successfully processed and saved: %s", tsv_path)

        except requests.exceptions.RequestException as e:
            logger.error(
                "Network/HTTP error occurred while downloading %s: %s", filename, e
            )
            raise
        except Exception as e:
            logger.error(
                "An unexpected error occurred while processing %s: %s", filename, e
            )
            raise

    logger.info("All IMDb dataset tasks finished.")


if __name__ == "__main__":
    # Configure root logger format and level when executed directly
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    download_imdb_datasets()
