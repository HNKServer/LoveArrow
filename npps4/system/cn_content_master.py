"""Read-only access to CN-only event and multi-unit story master tables.

The exact CN 9.7.1 client master overlay is authoritative for these tables.
Player progression is stored only in NPPS4's main database.
"""

from __future__ import annotations

import dataclasses
import functools
import sqlite3
from ..tools import cn_honoka_master


@dataclasses.dataclass(frozen=True)
class EventScenarioMaster:
    event_scenario_id: int
    event_id: int
    chapter: int
    chapter_asset: str | None
    title: str
    title_en: str | None
    open_date: str
    cost_type: int
    item_id: int
    amount: int


@dataclasses.dataclass(frozen=True)
class MultiUnitScenarioMaster:
    multi_unit_scenario_id: int
    multi_unit_id: int
    chapter: int
    chapter_asset: str | None
    unlocked_live_difficulty_id: int | None
    release_type: int | None
    button_asset: str
    button_asset_en: str | None
    title: str
    title_en: str | None
    open_date: str


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@functools.lru_cache(maxsize=1)
def event_scenarios() -> tuple[EventScenarioMaster, ...]:
    path = cn_honoka_master.bundled_cn_client_master_db()
    with sqlite3.connect(path) as db:
        rows = db.execute(
            """
            SELECT event_scenario_id, event_id, chapter, chapter_asset, title, title_en, open_date,
                   cost_type, item_id, amount
            FROM event_scenario_m
            ORDER BY event_id, chapter, event_scenario_id
            """
        ).fetchall()
    return tuple(
        EventScenarioMaster(
            event_scenario_id=_as_int(r[0]),
            event_id=_as_int(r[1]),
            chapter=_as_int(r[2]),
            chapter_asset=r[3],
            title=str(r[4] or ""),
            title_en=str(r[5]) if r[5] is not None else None,
            open_date=str(r[6] or "1970/01/01 00:00:00"),
            # Old event rows predate item-cost story release.  The client schema
            # still requires these numeric fields, so use the historical story
            # item defaults only when the master value is NULL.
            cost_type=_as_int(r[7], 1000) if r[7] is not None else 1000,
            item_id=_as_int(r[8], 1200) if r[8] is not None else 1200,
            amount=_as_int(r[9], 1) if r[9] is not None else 1,
        )
        for r in rows
    )


@functools.lru_cache(maxsize=1)
def multi_unit_scenarios() -> tuple[MultiUnitScenarioMaster, ...]:
    path = cn_honoka_master.bundled_cn_client_master_db()
    with sqlite3.connect(path) as db:
        rows = db.execute(
            """
            SELECT s.multi_unit_scenario_id, s.multi_unit_id, s.chapter, s.chapter_asset,
                   s.unlocked_live_difficulty_id, s.release_type,
                   o.multi_unit_scenario_btn_asset, o.multi_unit_scenario_btn_asset_en,
                   s.title, s.title_en, o.open_date
            FROM multi_unit_scenario_m AS s
            LEFT JOIN multi_unit_scenario_open_m AS o
              ON o.multi_unit_id = s.multi_unit_id
            ORDER BY s.multi_unit_id, s.chapter, s.multi_unit_scenario_id
            """
        ).fetchall()
    return tuple(
        MultiUnitScenarioMaster(
            multi_unit_scenario_id=_as_int(r[0]),
            multi_unit_id=_as_int(r[1]),
            chapter=_as_int(r[2]),
            chapter_asset=str(r[3]) if r[3] is not None else None,
            unlocked_live_difficulty_id=_as_int(r[4]) if r[4] is not None else None,
            release_type=_as_int(r[5]) if r[5] is not None else None,
            button_asset=str(r[6] or ""),
            button_asset_en=str(r[7]) if r[7] is not None else None,
            title=str(r[8] or ""),
            title_en=str(r[9]) if r[9] is not None else None,
            open_date=str(r[10] or "1970/01/01 00:00:00"),
        )
        for r in rows
    )


def event_by_id(event_scenario_id: int) -> EventScenarioMaster | None:
    return next((row for row in event_scenarios() if row.event_scenario_id == event_scenario_id), None)


def multi_by_id(multi_unit_scenario_id: int) -> MultiUnitScenarioMaster | None:
    return next(
        (row for row in multi_unit_scenarios() if row.multi_unit_scenario_id == multi_unit_scenario_id), None
    )
