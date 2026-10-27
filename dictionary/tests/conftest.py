"""Shared fixtures."""

import polars as pl
import pytest

from rimario_build import config, export


@pytest.fixture(scope="session")
def built_rows() -> pl.DataFrame:
    """The committed output CSV; skips the test when there is no build yet."""
    rows = export.read_csv(config.OUT_CSV)
    if rows.is_empty():
        pytest.skip(f"{config.OUT_CSV.name} not built yet")
    return rows
