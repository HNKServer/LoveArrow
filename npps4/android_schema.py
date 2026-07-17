"""Android-safe schema initialization for the mutable NPPS4 server DB.

Desktop NPPS4 uses Alembic to migrate ``data/main.sqlite3``. Alembic is a
path-oriented script runner and is awkward inside Chaquopy, where Python modules
may live inside the APK rather than as normal files. This module replaces
runtime Alembic on Android only.

The goal is not to invent a new schema.  For a fresh database, we create the
same current-head schema from NPPS4's SQLAlchemy metadata and then stamp the
schema with the current Alembic head.  For an existing database, we reconcile
missing tables, indexes and safe missing columns, and fail loudly instead of
silently corrupting data when an unsafe migration would be required.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Iterable

import sqlalchemy
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.schema import CreateColumn
from sqlalchemy.ext.asyncio import AsyncConnection

ALEMBIC_HEAD = "cn_post_service_content"
ANDROID_SCHEMA_REVISION = "android_schema_head_cn_post_service_content_v1"


def _sqlite_db_path_from_url(url: str, root_dir: str) -> Path | None:
    parsed = sqlalchemy.engine.url.make_url(url)
    if not parsed.get_backend_name().startswith("sqlite"):
        return None
    if not parsed.database:
        return None
    db_path = Path(parsed.database)
    if not db_path.is_absolute():
        db_path = Path(root_dir) / db_path
    return db_path


def _ensure_sqlite_pragmas(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path, isolation_level=None) as db:
        # Match the desktop Alembic env.py behavior for SQLite.
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table_has_rows(conn, table_name: str) -> bool:
    try:
        return bool(conn.exec_driver_sql(f"SELECT 1 FROM {_quote_ident(table_name)} LIMIT 1").first())
    except Exception:
        return False


def _column_sql(column: sqlalchemy.Column, dialect) -> str:
    # CreateColumn produces fragments such as 'foo INTEGER NOT NULL'.
    return str(CreateColumn(column).compile(dialect=dialect))


def _add_missing_column_if_safe(conn, table_name: str, column: sqlalchemy.Column) -> None:
    """Add a missing column when SQLite can do so safely.

    SQLite cannot add NOT NULL columns to non-empty tables unless they have a
    server default.  In that case, refusing is safer than creating a subtly
    broken DB.  Fresh DB creation is handled by create_all; this path only
    matters for upgrades from previous Android wrapper builds.
    """
    non_empty = _table_has_rows(conn, table_name)
    has_default = column.server_default is not None or column.default is not None
    if non_empty and not column.nullable and not has_default:
        raise RuntimeError(
            f"Existing Android database table '{table_name}' is missing required column "
            f"'{column.name}', and the table already contains data. This needs an explicit "
            "programmatic migration or a fresh DB restore; refusing to corrupt saved progress."
        )

    col_sql = _column_sql(column.copy(), conn.dialect)
    conn.exec_driver_sql(f"ALTER TABLE {_quote_ident(table_name)} ADD COLUMN {col_sql}")


def _reconcile_metadata(sync_conn, metadata: sqlalchemy.MetaData) -> None:
    """Create missing tables, indexes and safe missing columns.

    This makes upgrades from earlier Android wrapper builds more reliable than a
    bare metadata.create_all(), while still avoiding Alembic's filesystem path
    requirements. It intentionally does not perform destructive changes.
    """
    inspector = sa_inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())

    for table in metadata.sorted_tables:
        if table.name not in existing_tables:
            table.create(bind=sync_conn, checkfirst=True)
            continue

        existing_cols = {col["name"] for col in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name not in existing_cols:
                _add_missing_column_if_safe(sync_conn, table.name, column)

        # Create missing indexes. SQLite autoindexes constraints internally, so
        # only explicitly declared metadata indexes are considered here.
        existing_indexes = {idx["name"] for idx in inspector.get_indexes(table.name)}
        for index in table.indexes:
            if index.name and index.name not in existing_indexes:
                index.create(bind=sync_conn, checkfirst=True)


def _stamp_head(sync_conn) -> None:
    sync_conn.exec_driver_sql(
        "CREATE TABLE IF NOT EXISTS alembic_version "
        "(version_num VARCHAR(32) NOT NULL, CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
    )
    sync_conn.exec_driver_sql("DELETE FROM alembic_version")
    sync_conn.exec_driver_sql("INSERT INTO alembic_version (version_num) VALUES (?)", (ALEMBIC_HEAD,))

    # migration_fixes is part of the normal NPPS4 schema.  Mark that this DB was
    # initialized by the Android schema path; this is useful for diagnostics and
    # backup migration logic.
    try:
        sync_conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS migration_fixes "
            "(revision VARCHAR NOT NULL, PRIMARY KEY (revision))"
        )
        sync_conn.exec_driver_sql(
            "INSERT OR IGNORE INTO migration_fixes (revision) VALUES (?)", (ANDROID_SCHEMA_REVISION,)
        )
    except Exception:
        # Do not break startup just because the diagnostic marker failed.
        pass


async def ensure_schema_async() -> None:
    import npps4.config.config as cfg
    import npps4.db.common as db_common
    import npps4.db.main as db_main

    db_path = _sqlite_db_path_from_url(cfg.get_database_url(), cfg.ROOT_DIR)
    if db_path is not None:
        _ensure_sqlite_pragmas(db_path)

    async with db_main.engine.begin() as conn:
        await conn.run_sync(_ensure_schema_sync, db_common.Base.metadata)


def _ensure_schema_sync(sync_conn, metadata: sqlalchemy.MetaData) -> None:
    _reconcile_metadata(sync_conn, metadata)
    _stamp_head(sync_conn)


def ensure_schema() -> None:
    asyncio.run(ensure_schema_async())
