"""Fixtures shared by the test modules."""

import pytest
from loguru import logger

from movierec.api import main


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """Each test starts with every client's rate limit untouched."""
    main.recommend_limiter.reset()


@pytest.fixture
def log_records():
    """Every loguru record written during the test, as loguru's record dicts."""
    records = []
    sink_id = logger.add(lambda message: records.append(message.record), level=0)
    yield records
    logger.remove(sink_id)
