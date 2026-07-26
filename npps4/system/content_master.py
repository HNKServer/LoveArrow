"""Profile-aware read-only master provider for post-service story content.

CN uses the exact 9.7.1 combined client master already bundled by the fork.
GL uses the final post-merge client event and multi-unit master databases.
Player progression remains in NPPS4's mutable main database and is selected by
``context.profile``; only immutable catalogue lookup lives here.
"""
from __future__ import annotations

from contextlib import closing

import dataclasses
import functools
import importlib.resources as resources
import os
import sqlite3
from pathlib import Path

from .. import client_profile, util
from ..download import download
from . import cn_content_master

EventScenarioMaster = cn_content_master.EventScenarioMaster
MultiUnitScenarioMaster = cn_content_master.MultiUnitScenarioMaster


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_sqlite(path: str | os.PathLike[str]) -> bool:
    try:
        with open(path, "rb") as stream:
            return stream.read(16) == b"SQLite format 3\0"
    except OSError:
        return False


def _bundled_gl_path(name: str) -> str:
    ref = resources.files("npps4.assets.gl_content_master").joinpath(f"{name}.sqlite")
    # Chaquopy installs package data as ordinary files.  ``as_file`` is not
    # retained outside its context, so reject non-filesystem package loaders
    # loudly rather than returning a transient path.
    path = Path(str(ref))
    if not path.is_file():
        raise RuntimeError(f"Bundled GL content master is unavailable: {name}")
    return str(path)


def _gl_path(name: str) -> str:
    """Prefer an active GL backend DB when it is already plain SQLite.

    Public DLAPI ``getdb`` responses are normally decrypted SQLite files.  Raw
    client archives may instead expose Honky-encrypted ``.db_`` files; those are
    not opened directly and the audited bundled final-service catalogue is used
    as the fallback.
    """
    try:
        candidate = download.get_db_path(name, profile=client_profile.ClientProfile.GL)
        if _is_sqlite(candidate):
            return candidate
    except Exception as exc:
        util.log(
            "GL content master backend fallback",
            f"database={name}",
            f"error={exc!r}",
            severity=util.logging.INFO,
        )
    return _bundled_gl_path(name)


@functools.lru_cache(maxsize=4)
def _gl_event_scenarios(path: str, mtime_ns: int) -> tuple[EventScenarioMaster, ...]:
    del mtime_ns
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute(
            """
            SELECT event_scenario_id, event_id, chapter,
                   COALESCE(chapter_asset_en, chapter_asset), title, title_en,
                   open_date, cost_type, item_id, amount
              FROM event_scenario_m
             ORDER BY event_id, chapter, event_scenario_id
            """
        ).fetchall()
    result = tuple(
        EventScenarioMaster(
            event_scenario_id=_as_int(row[0]),
            event_id=_as_int(row[1]),
            chapter=_as_int(row[2]),
            chapter_asset=str(row[3]) if row[3] is not None else None,
            title=str(row[4] or ""),
            title_en=str(row[5]) if row[5] is not None else None,
            open_date=str(row[6] or "1970/01/01 00:00:00"),
            cost_type=_as_int(row[7], 1000) if row[7] is not None else 1000,
            item_id=_as_int(row[8], 1200) if row[8] is not None else 1200,
            amount=_as_int(row[9], 1) if row[9] is not None else 1,
        )
        for row in rows
    )
    if len(result) != 755:
        raise RuntimeError(f"Unexpected GL event-scenario catalogue size: {len(result)}")
    return result


@functools.lru_cache(maxsize=4)
def _gl_multi_unit_scenarios(path: str, mtime_ns: int) -> tuple[MultiUnitScenarioMaster, ...]:
    del mtime_ns
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute(
            """
            SELECT s.multi_unit_scenario_id, s.multi_unit_id, s.chapter,
                   COALESCE(s.chapter_asset_en, s.chapter_asset),
                   s.unlocked_live_difficulty_id, s.release_type,
                   o.multi_unit_scenario_btn_asset,
                   o.multi_unit_scenario_btn_asset_en,
                   s.title, s.title_en, o.open_date
              FROM multi_unit_scenario_m AS s
              LEFT JOIN multi_unit_scenario_open_m AS o
                ON o.multi_unit_id = s.multi_unit_id
             ORDER BY s.multi_unit_id, s.chapter, s.multi_unit_scenario_id
            """
        ).fetchall()
    result = tuple(
        MultiUnitScenarioMaster(
            multi_unit_scenario_id=_as_int(row[0]),
            multi_unit_id=_as_int(row[1]),
            chapter=_as_int(row[2]),
            chapter_asset=str(row[3]) if row[3] is not None else None,
            unlocked_live_difficulty_id=_as_int(row[4]) if row[4] is not None else None,
            release_type=_as_int(row[5]) if row[5] is not None else None,
            button_asset=str(row[6] or ""),
            button_asset_en=str(row[7]) if row[7] is not None else None,
            title=str(row[8] or ""),
            title_en=str(row[9]) if row[9] is not None else None,
            open_date=str(row[10] or "1970/01/01 00:00:00"),
        )
        for row in rows
    )
    if len(result) != 57:
        raise RuntimeError(f"Unexpected GL multi-unit catalogue size: {len(result)}")
    return result


def event_scenarios(profile: client_profile.ClientProfile | str) -> tuple[EventScenarioMaster, ...]:
    normalized = client_profile.ClientProfile.normalize(profile)
    if normalized is client_profile.ClientProfile.CN:
        return cn_content_master.event_scenarios()
    path = _gl_path("event_common")
    return _gl_event_scenarios(path, os.stat(path).st_mtime_ns)


def multi_unit_scenarios(profile: client_profile.ClientProfile | str) -> tuple[MultiUnitScenarioMaster, ...]:
    normalized = client_profile.ClientProfile.normalize(profile)
    if normalized is client_profile.ClientProfile.CN:
        return cn_content_master.multi_unit_scenarios()
    path = _gl_path("multi_unit_scenario")
    return _gl_multi_unit_scenarios(path, os.stat(path).st_mtime_ns)


def event_by_id(
    profile: client_profile.ClientProfile | str, event_scenario_id: int
) -> EventScenarioMaster | None:
    return next(
        (row for row in event_scenarios(profile) if row.event_scenario_id == event_scenario_id),
        None,
    )


def multi_by_id(
    profile: client_profile.ClientProfile | str, multi_unit_scenario_id: int
) -> MultiUnitScenarioMaster | None:
    return next(
        (
            row
            for row in multi_unit_scenarios(profile)
            if row.multi_unit_scenario_id == multi_unit_scenario_id
        ),
        None,
    )
