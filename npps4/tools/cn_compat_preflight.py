"""CN compatibility preflight and static/synthetic readiness checks.

This module is intentionally conservative: it does not modify user state and it
is safe to expose as a diagnostic endpoint.  It checks the exact class of issues
that repeatedly appeared while adapting the CN 9.7.x/honoka flow to NPPS4:

* editable external providers shadowed by placeholders;
* server_data.json parses but references missing master-data rows;
* generated CN split DBs exist but are semantically incomplete;
* CN bootstrap/main-screen route coverage is present but still running NPPS4
  native assumptions.

It is not a replacement for real client testing, but it moves failures from
"client crashes after five retries" to "preflight says which contract is broken".
"""

from __future__ import annotations

import asyncio
import inspect
import os
import runpy
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Issue:
    severity: str
    area: str
    message: str
    detail: dict[str, Any] | None = None

    def asdict(self) -> dict[str, Any]:
        out = {"severity": self.severity, "area": self.area, "message": self.message}
        if self.detail:
            out["detail"] = self.detail
        return out


def _issue(issues: list[Issue], severity: str, area: str, message: str, **detail: Any) -> None:
    issues.append(Issue(severity, area, message, detail or None))


def _callable_in_file(path: str, names: list[str]) -> tuple[bool, str]:
    if not os.path.isfile(path):
        return False, "missing file"
    try:
        ns = runpy.run_path(path)
    except Exception as exc:
        return False, f"load error: {type(exc).__name__}: {exc}"
    missing = [name for name in names if not callable(ns.get(name))]
    if missing:
        return False, "missing callables: " + ", ".join(missing)
    return True, "ok"


def _check_external_providers(issues: list[Issue]) -> dict[str, Any]:
    from npps4.config import config

    providers = {
        "badwords": (config.BADWORDS_CHECK_FILE, ["has_badwords"]),
        "login_bonus": (config._LOGIN_BONUS_FILE, ["get_rewards"]),
        "beatmap": (config.BEATMAP_PROVIDER_FILE, ["get_beatmap_data", "randomize_beatmaps"]),
        "live_unit_drop": (config.LIVE_UNIT_DROP_FILE, ["get_live_drop_unit"]),
        "live_box_drop": (config.LIVE_BOX_DROP_FILE, ["process_effort_box"]),
    }
    out: dict[str, Any] = {}
    for name, (path, required) in providers.items():
        ok, reason = _callable_in_file(path, required)
        out[name] = {"path": path, "required": required, "ok": ok, "reason": reason}
        if not ok:
            _issue(
                issues,
                "error",
                "external_provider",
                f"external/{name}.py is not a valid NPPS4 provider: {reason}",
                path=path,
                required=required,
            )
    return out


def _db_path(db_name: str) -> str | None:
    # Prefer the active download backend because cn_archive may generate and use
    # data/db_cn_honoka even when config.toml's db_root still points at an empty
    # user-managed directory.
    try:
        from npps4.download import download
        p = download.get_db_path(db_name)
        if p and os.path.isfile(p):
            return p
    except Exception:
        pass

    try:
        from npps4.config import config
        root = getattr(config.CONFIG_DATA.download.cn_archive, "db_root", "") or ""
        if root:
            for candidate in (f"{db_name}.db_", f"{db_name}.db", db_name):
                p = os.path.join(root, candidate)
                if os.path.isfile(p):
                    return p
        gen_root = os.path.join(config.get_data_directory(), "db_cn_honoka")
        for candidate in (f"{db_name}.db_", f"{db_name}.db", db_name):
            p = os.path.join(gen_root, candidate)
            if os.path.isfile(p):
                return p
    except Exception:
        pass
    return None


def _scalar(db_name: str, sql: str, args: tuple[Any, ...] = ()) -> Any:
    path = _db_path(db_name)
    if not path:
        raise RuntimeError(f"{db_name}.db_ not found")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
        return conn.execute(sql, args).fetchone()[0]


def _exists(db_name: str, table: str, pk_col: str, value: int) -> bool:
    try:
        return bool(_scalar(db_name, f'SELECT COUNT(*) FROM "{table}" WHERE "{pk_col}" = ?', (int(value),)))
    except Exception:
        return False


def _table_count(db_name: str, table: str) -> int | None:
    try:
        return int(_scalar(db_name, f'SELECT COUNT(*) FROM "{table}"'))
    except Exception:
        return None


_ITEM_REF_MAP: dict[int, tuple[str, str, str] | None] = {
    1000: ("item", "kg_item_m", "item_id"),
    1001: ("unit", "unit_m", "unit_id"),
    1002: ("unit", "unit_removable_skill_m", "unit_removable_skill_id"),
    3000: None,  # G / game coin
    3001: None,  # Loveca
    3002: None,  # social point
    3006: ("exchange", "exchange_point_m", "exchange_point_id"),
    5000: ("live", "live_track_m", "live_track_id"),
    5100: ("item", "award_m", "award_id"),
    5200: ("item", "background_m", "background_id"),
    5300: ("scenario", "scenario_m", "scenario_id"),
    5500: ("unit", "unit_removable_skill_m", "unit_removable_skill_id"),
    8000: ("item", "recovery_item_m", "recovery_item_id"),
    14000: ("museum", "museum_contents_m", "museum_contents_id"),
}


def _check_item_ref(issues: list[Issue], area: str, add_type: int, item_id: int, label: str) -> bool:
    mapping = _ITEM_REF_MAP.get(int(add_type), "unknown")
    if mapping is None:
        return True
    if mapping == "unknown":
        _issue(issues, "warn", area, f"{label} uses add_type {add_type}, which the preflight does not know how to validate", add_type=add_type, item_id=item_id)
        return True
    db_name, table, pk = mapping
    if not _exists(db_name, table, pk, int(item_id)):
        _issue(issues, "error", area, f"{label} references missing master-data row {db_name}.{table}.{pk}={item_id}", add_type=add_type, item_id=item_id)
        return False
    return True


def _check_server_data_semantics(issues: list[Issue]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        from npps4 import data as server_data
        sd = server_data.get()
    except Exception as exc:
        _issue(issues, "error", "server_data", f"server_data.json cannot be parsed/loaded: {type(exc).__name__}: {exc}")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    out["badwords"] = len(sd.badwords)
    out["achievement_reward"] = len(sd.achievement_reward)
    out["common_live_unit_drops"] = len(sd.common_live_unit_drops)
    out["live_specific_live_unit_drops"] = len(sd.live_specific_live_unit_drops)
    out["live_effort_drops"] = sorted(sd.live_effort_drops.keys())
    out["secretbox_data"] = len(sd.secretbox_data)
    out["sticker_shop"] = len(sd.sticker_shop)

    if not sd.common_live_unit_drops:
        _issue(issues, "error", "server_data", "common_live_unit_drops is empty; live result reward generation can loop forever or fail")
    if not sd.live_effort_drops:
        _issue(issues, "error", "server_data", "live_effort_drops is empty; /lbonus/execute and live reward boxes cannot complete")

    for box_id, drops in sd.live_effort_drops.items():
        if not _exists("effort", "live_effort_point_box_spec_m", "live_effort_point_box_spec_id", box_id):
            _issue(issues, "error", "masterdata", f"server_data.live_effort_drops references missing effort box spec id {box_id}", live_effort_point_box_spec_id=box_id)
        if not drops:
            _issue(issues, "warn", "server_data", f"live_effort_drops[{box_id}] is empty")
        for index, drop in enumerate(drops[:80]):
            _check_item_ref(issues, "server_data", int(drop.add_type), int(drop.item_id), f"live_effort_drops[{box_id}][{index}]")

    for index, drop in enumerate(sd.common_live_unit_drops[:500]):
        if not _exists("unit", "unit_m", "unit_id", int(drop.unit_id)):
            _issue(issues, "error", "server_data", f"common_live_unit_drops[{index}] references missing unit_id {drop.unit_id}", unit_id=drop.unit_id)

    for live_setting_id, drops in list(sd.live_specific_live_unit_drops.items())[:1500]:
        if not _exists("live", "live_setting_m", "live_setting_id", int(live_setting_id)):
            _issue(issues, "warn", "server_data", f"live_specific_live_unit_drops references missing live_setting_id {live_setting_id}", live_setting_id=live_setting_id)
        for index, drop in enumerate(drops[:20]):
            if not _exists("unit", "unit_m", "unit_id", int(drop.unit_id)):
                _issue(issues, "error", "server_data", f"live_specific_live_unit_drops[{live_setting_id}][{index}] references missing unit_id {drop.unit_id}", unit_id=drop.unit_id)

    for sb_id, sb in list(sd.secretbox_data.items())[:80]:
        for pool_index, pool in enumerate(sb.rarity_pools):
            for uid in pool[:200]:
                if not _exists("unit", "unit_m", "unit_id", int(uid)):
                    _issue(issues, "warn", "server_data", f"secretbox {sb_id} rarity_pool[{pool_index}] references missing unit_id {uid}", secretbox_id=sb_id, unit_id=uid)
                    break

    return out


def _check_masterdata_basics(issues: list[Issue]) -> dict[str, Any]:
    required_tables = {
        "game_mater": ["game_setting_m", "strings_m", "add_type_m"],
        "unit": ["unit_m", "unit_rarity_m", "unit_attribute_m", "unit_level_up_pattern_m"],
        "live": ["live_track_m", "live_setting_m", "normal_live_m", "live_goal_reward_m"],
        "item": ["award_m", "background_m"],
        "scenario": ["scenario_m"],
        "subscenario": ["subscenario_m"],
        "achievement": ["achievement_m"],
        "exchange": ["exchange_point_m"],
        "museum": ["museum_contents_m"],
        "effort": ["live_effort_point_box_spec_m"],
    }
    out: dict[str, Any] = {}
    for db_name, tables in required_tables.items():
        db_path = _db_path(db_name)
        out[db_name] = {"path": db_path, "tables": {}}
        if not db_path:
            _issue(issues, "error", "masterdata", f"{db_name}.db_ is missing")
            continue
        for table in tables:
            count = _table_count(db_name, table)
            out[db_name]["tables"][table] = count
            if count is None:
                _issue(issues, "error", "masterdata", f"{db_name}.{table} is missing or unreadable")
            elif count == 0:
                sev = "warn"
                if table in {"game_setting_m", "strings_m", "unit_m", "live_setting_m", "live_effort_point_box_spec_m"}:
                    sev = "error"
                _issue(issues, sev, "masterdata", f"{db_name}.{table} has no rows")

    # Initial member screen uses these hard-coded NPPS4 starter IDs.  If any is
    # missing, login/unitSelect will fail immediately after the user taps a card.
    try:
        from npps4.game.login import INITIAL_UNIT_IDS, TEMPLATE_DECK
        starter_missing: list[int] = []
        for group in INITIAL_UNIT_IDS:
            for center_uid in group:
                deck = list(TEMPLATE_DECK)
                deck[4] = center_uid
                for uid in deck:
                    if uid and not _exists("unit", "unit_m", "unit_id", int(uid)):
                        starter_missing.append(int(uid))
        if starter_missing:
            _issue(issues, "error", "masterdata", "starter unit selection references unit_id values absent from unit.db_", missing=sorted(set(starter_missing))[:100])
        out["starter_units"] = {"missing": sorted(set(starter_missing))}
    except Exception as exc:
        _issue(issues, "warn", "masterdata", f"could not check starter units: {type(exc).__name__}: {exc}")
    return out


def _check_route_coverage(issues: list[Issue]) -> dict[str, Any]:
    expected = [
        ("login", "authkey"), ("login", "login"), ("login", "startUp"),
        ("user", "changeName"), ("login", "unitList"), ("login", "unitSelect"),
        ("tutorial", "progress"), ("tutorial", "skip"), ("lbonus", "execute"),
        ("login", "topInfo"), ("login", "topInfoOnce"), ("user", "userInfo"),
        ("unit", "unitAll"), ("unit", "deckInfo"), ("reward", "list"),
        ("notice", "noticeList"), ("banner", "list"), ("friend", "friendList"),
        ("live", "liveStatus"), ("live", "play"), ("live", "reward"),
    ]
    out: dict[str, Any] = {}
    try:
        from npps4.idol.core import API_ROUTER_MAP
        routes = {f"{m}/{a}" for (m, a) in API_ROUTER_MAP.keys()}
        missing = [f"{m}/{a}" for (m, a) in expected if (m, a) not in API_ROUTER_MAP]
        out = {"expected": [f"{m}/{a}" for m, a in expected], "missing": missing, "registered_count": len(API_ROUTER_MAP)}
        for route in missing:
            _issue(issues, "error", "route", f"CN bootstrap/main-screen expected route is not registered: {route}")
    except Exception as exc:
        _issue(issues, "warn", "route", f"could not inspect NPPS4 route map: {type(exc).__name__}: {exc}")
        out = {"error": f"{type(exc).__name__}: {exc}"}
    return out


def run_cn_preflight() -> dict[str, Any]:
    from npps4.config import config

    issues: list[Issue] = []
    result: dict[str, Any] = {
        "enabled": bool(config.is_cn_compat()),
        "region": getattr(config.CONFIG_DATA.compat, "region", ""),
        "download_backend": getattr(config.CONFIG_DATA.download, "backend", ""),
    }
    if not config.is_cn_compat():
        result["summary"] = {"errors": 0, "warnings": 0}
        result["issues"] = []
        return result

    result["external_providers"] = _check_external_providers(issues)
    result["masterdata"] = _check_masterdata_basics(issues)
    result["server_data"] = _check_server_data_semantics(issues)
    result["routes"] = _check_route_coverage(issues)

    errors = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warn")
    result["summary"] = {"errors": errors, "warnings": warnings, "ok": errors == 0}
    result["issues"] = [i.asdict() for i in issues]
    return result


def run_cn_preflight_json() -> str:
    import json
    return json.dumps(run_cn_preflight(), ensure_ascii=False, indent=2)


if __name__ == "__main__":
    print(run_cn_preflight_json())
