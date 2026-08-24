"""Application bootstrap service for infrastructure readiness."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from config.settings import DATABASE_PATH
from src.database.connection import Database


@dataclass(frozen=True)
class CoreStatus:
    database_ready: bool
    database_path: str
    schema_version: int
    table_count: int


@lru_cache(maxsize=4)
def get_database(path: str = str(DATABASE_PATH)) -> Database:
    return Database(Path(path))


def initialize_core(path: Path = DATABASE_PATH) -> CoreStatus:
    database = get_database(str(path))
    status = database.initialize()
    return CoreStatus(
        database_ready=True,
        database_path=status.path,
        schema_version=status.schema_version,
        table_count=len(status.tables),
    )
