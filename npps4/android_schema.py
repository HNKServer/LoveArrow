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

from contextlib import closing

import asyncio
import os
import sqlite3
from pathlib import Path
from typing import Iterable

import sqlalchemy
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.schema import CreateColumn
from sqlalchemy.ext.asyncio import AsyncConnection

ALEMBIC_HEAD = "costume_full_cycle"
ANDROID_SCHEMA_REVISION = "android_schema_head_costume_full_cycle_v1"


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
    with closing(sqlite3.connect(db_path, isolation_level=None)) as db:
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




def _column_names(sync_conn, table_name: str) -> set[str]:
    rows = sync_conn.exec_driver_sql(f"PRAGMA table_info({_quote_ident(table_name)})").all()
    return {str(row[1]) for row in rows}


def _unique_index_columns(sync_conn, table_name: str) -> set[tuple[str, ...]]:
    result: set[tuple[str, ...]] = set()
    for row in sync_conn.exec_driver_sql(f"PRAGMA index_list({_quote_ident(table_name)})").all():
        if not bool(row[2]):
            continue
        index_name = str(row[1])
        cols = tuple(
            str(info[2])
            for info in sync_conn.exec_driver_sql(f"PRAGMA index_info({_quote_ident(index_name)})").all()
        )
        result.add(cols)
    return result


def _rebuild_story_table(sync_conn, table_name: str, id_column: str, default_profile: str) -> None:
    columns = _column_names(sync_conn, table_name)
    expected_unique = ("user_id", "profile", id_column)
    if "profile" in columns and expected_unique in _unique_index_columns(sync_conn, table_name):
        return

    temp = f"{table_name}__android_profile_new"
    sync_conn.exec_driver_sql(f'DROP TABLE IF EXISTS {_quote_ident(temp)}')
    sync_conn.exec_driver_sql(
        f'''CREATE TABLE {_quote_ident(temp)} (
            id INTEGER NOT NULL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            profile VARCHAR NOT NULL,
            {_quote_ident(id_column)} INTEGER NOT NULL,
            completed BOOLEAN NOT NULL,
            is_new BOOLEAN NOT NULL,
            insert_date INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES user(id),
            UNIQUE(user_id, profile, {_quote_ident(id_column)})
        )'''
    )
    profile_expr = "profile" if "profile" in columns else ":default_profile"
    sync_conn.exec_driver_sql(
        f'''INSERT INTO {_quote_ident(temp)}
            (id, user_id, profile, {_quote_ident(id_column)}, completed, is_new, insert_date)
            SELECT id, user_id, {profile_expr}, {_quote_ident(id_column)}, completed, is_new, insert_date
              FROM {_quote_ident(table_name)}''',
        {"default_profile": default_profile},
    )
    sync_conn.exec_driver_sql(f'DROP TABLE {_quote_ident(table_name)}')
    sync_conn.exec_driver_sql(
        f'ALTER TABLE {_quote_ident(temp)} RENAME TO {_quote_ident(table_name)}'
    )



def _rebuild_museum_table(sync_conn, default_profile: str) -> None:
    table_name = "museum_unlock"
    columns = _column_names(sync_conn, table_name)
    expected_unique = ("user_id", "profile", "museum_contents_id")
    if "profile" in columns and expected_unique in _unique_index_columns(sync_conn, table_name):
        return

    temp = "museum_unlock__android_profile_new"
    sync_conn.exec_driver_sql(f'DROP TABLE IF EXISTS {_quote_ident(temp)}')
    sync_conn.exec_driver_sql(
        f'''CREATE TABLE {_quote_ident(temp)} (
            id INTEGER NOT NULL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            profile VARCHAR NOT NULL,
            museum_contents_id INTEGER NOT NULL,
            FOREIGN KEY(user_id) REFERENCES user(id),
            UNIQUE(user_id, profile, museum_contents_id)
        )'''
    )
    if "profile" in columns:
        sync_conn.exec_driver_sql(
            f'''INSERT INTO {_quote_ident(temp)}
                (id, user_id, profile, museum_contents_id)
                SELECT id, user_id, profile, museum_contents_id
                  FROM {_quote_ident(table_name)}'''
        )
    else:
        # The legacy Android table represented one shared unlock set. Its rows
        # cannot be attributed to CN or GL after the fact, so retain them in both
        # profile-specific sets. Native Master filtering prevents cross-region IDs
        # from being exposed by museum/info.
        for profile in ("cn", "gl"):
            sync_conn.exec_driver_sql(
                f'''INSERT INTO {_quote_ident(temp)}
                    (user_id, profile, museum_contents_id)
                    SELECT user_id, :profile, museum_contents_id
                      FROM {_quote_ident(table_name)}''',
                {"profile": profile},
            )
    sync_conn.exec_driver_sql(f'DROP TABLE {_quote_ident(table_name)}')
    sync_conn.exec_driver_sql(
        f'ALTER TABLE {_quote_ident(temp)} RENAME TO {_quote_ident(table_name)}'
    )

def _migrate_dual_profile_schema(sync_conn, default_profile: str) -> None:
    inspector = sa_inspect(sync_conn)
    tables = set(inspector.get_table_names())
    if "session" in tables:
        session_columns = _column_names(sync_conn, "session")
        if "profile" not in session_columns:
            escaped = default_profile.replace("'", "''")
            sync_conn.exec_driver_sql(
                f"ALTER TABLE session ADD COLUMN profile VARCHAR NOT NULL DEFAULT '{escaped}'"
            )
        if "server_rsa_label" not in session_columns:
            sync_conn.exec_driver_sql("ALTER TABLE session ADD COLUMN server_rsa_label VARCHAR")

    if "event_scenario_unlock" in tables:
        _rebuild_story_table(sync_conn, "event_scenario_unlock", "event_scenario_id", default_profile)
    if "multi_unit_scenario_unlock" in tables:
        _rebuild_story_table(
            sync_conn, "multi_unit_scenario_unlock", "multi_unit_scenario_id", default_profile
        )
    if "museum_unlock" in tables:
        _rebuild_museum_table(sync_conn, default_profile)


def _migrate_user_identities(sync_conn, default_profile: str) -> None:
    inspector = sa_inspect(sync_conn)
    tables = set(inspector.get_table_names())
    if not {"user", "user_client_identity"}.issubset(tables):
        return
    user_columns = _column_names(sync_conn, "user")
    if not {"id", "key", "passwd", "insert_date", "update_date"}.issubset(user_columns):
        return
    sync_conn.exec_driver_sql(
        '''INSERT INTO user_client_identity
               (user_id, profile, login_key, passwd, external_user_id, insert_date, update_date)
           SELECT u.id, :profile, u."key", u.passwd, NULL, u.insert_date, u.update_date
             FROM user AS u
            WHERE u."key" IS NOT NULL
              AND NOT EXISTS (
                    SELECT 1 FROM user_client_identity AS i
                     WHERE i.user_id = u.id AND i.profile = :profile
              )''',
        {"profile": default_profile},
    )


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
        await conn.run_sync(_ensure_schema_sync, db_common.Base.metadata, cfg.get_default_profile().value)


def _ensure_schema_sync(sync_conn, metadata: sqlalchemy.MetaData, default_profile: str) -> None:
    _migrate_dual_profile_schema(sync_conn, default_profile)
    _reconcile_metadata(sync_conn, metadata)
    _migrate_user_identities(sync_conn, default_profile)
    _stamp_head(sync_conn)


def ensure_schema() -> None:
    asyncio.run(ensure_schema_async())
