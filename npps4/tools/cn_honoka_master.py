"""Generate NPPS4-readable CN split master databases.

NPPS4's own table schemas remain authoritative.  For data rows, the converter
prefers complete tables extracted from the exact CN 9.7.1 client, and falls
back to honoka-chan's broader combined ``main.db`` only when the client overlay
does not contain a table.  This preserves NPPS4's full implementation while
using honoka as a compatibility/data source rather than replacing NPPS4 with
its hard-coded handlers.

The converter deliberately does not import :mod:`npps4.db` modules during the
offline conversion step because those modules open the active download backend
at import time.  It instead reads the embedded NPPS4 CREATE TABLE schemas,
creates each split SQLite file, copies matching columns, and seeds only the
small bootstrap rows which NPPS4 requires but neither source ships.
"""

from __future__ import annotations

import os
import re
import sqlite3
from contextlib import closing
from importlib import resources
from pathlib import Path
from typing import Iterable

DB_SOURCES: dict[str, str] = {
    "game_mater": "game_mater.py",
    "unit": "unit.py",
    "live": "live.py",
    "item": "item.py",
    "scenario": "scenario.py",
    "subscenario": "subscenario.py",
    "achievement": "achievement.py",
    "exchange": "exchange.py",
    "museum": "museum.py",
    "effort": "effort.py",
}

MANIFEST_TABLE = "_npps4_cn_honoka_manifest"
_CREATE_RE = re.compile(r"CREATE\s+TABLE\s+`([^`]+)`\s*\([\s\S]*?\n\s*\)", re.IGNORECASE)


def bundled_honoka_main_db() -> str:
    try:
        return str(resources.files("npps4.assets").joinpath("honoka_main.db"))
    except Exception:
        return str(Path(__file__).resolve().parents[1] / "assets" / "honoka_main.db")


def bundled_cn_client_master_db() -> str:
    """Return the exact CN 9.7.1 master-data overlay bundled with the server.

    honoka's combined main.db is still the broad fallback source, but several
    tables there are absent or reduced to a handful of columns.  The supplied
    CN APK contains complete achievement/live/scenario tables.  The overlay is
    a consolidated SQLite copy of those exact tables plus event and multi-unit
    story metadata.  It is read-only and never stores player state.
    """
    try:
        return str(resources.files("npps4.assets").joinpath("cn_client_master.db"))
    except Exception:
        return str(Path(__file__).resolve().parents[1] / "assets" / "cn_client_master.db")


def _db_source_file(db_name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "db" / DB_SOURCES[db_name]


def _create_sql_by_table(db_name: str) -> dict[str, str]:
    # Do not read npps4/db/*.py from __file__ at runtime. On Android, Chaquopy
    # can run bytecode from AssetFinder without extracting the original .py
    # files to normal filesystem paths, which caused FileNotFoundError for
    # npps4/db/game_mater.py. Use the generated embedded schema module first,
    # and keep source-file parsing only as a desktop fallback.
    try:
        from npps4.tools.cn_honoka_schema import SCHEMAS
        schema = SCHEMAS.get(db_name)
        if schema:
            return dict(schema)
    except Exception:
        pass

    src = _db_source_file(db_name).read_text(encoding="utf-8")
    out: dict[str, str] = {}
    for m in _CREATE_RE.finditer(src):
        table = m.group(1)
        sql = m.group(0)
        lines = sql.splitlines()
        min_indent = min((len(line) - len(line.lstrip(" ")) for line in lines if line.strip()), default=0)
        sql = "\n".join(line[min_indent:] for line in lines)
        out[table] = sql
    return out


def _source_tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _columns(conn: sqlite3.Connection, table: str):
    return conn.execute(f'PRAGMA table_info("{table}")').fetchall()


def _default_for_type(sql_type: str):
    t = (sql_type or "").upper()
    if "INT" in t:
        return 0
    if any(x in t for x in ("REAL", "FLOA", "DOUB", "NUM", "DEC")):
        return 0.0
    if "BLOB" in t:
        return b""
    return ""


def _value_for_missing_column(col_info):
    _cid, _name, sql_type, notnull, dflt_value, pk = col_info
    if dflt_value is not None and str(dflt_value).upper() != "NULL":
        raw = str(dflt_value)
        if (raw.startswith("'") and raw.endswith("'")) or (raw.startswith('"') and raw.endswith('"')):
            return raw[1:-1]
        try:
            return int(raw)
        except Exception:
            try:
                return float(raw)
            except Exception:
                return raw
    if notnull or pk:
        return _default_for_type(sql_type)
    return None


def _copy_table(src: sqlite3.Connection, dst: sqlite3.Connection, table: str) -> tuple[int, str]:
    src_cols_info = _columns(src, table)
    dst_cols_info = _columns(dst, table)
    if not src_cols_info or not dst_cols_info:
        return 0, "missing columns"

    src_cols = [c[1] for c in src_cols_info]
    dst_cols = [c[1] for c in dst_cols_info]
    common_cols = [c for c in dst_cols if c in src_cols]
    if not common_cols:
        return 0, "no common columns"

    src_select = ", ".join([f'"{c}"' for c in common_cols])
    rows = src.execute(f'SELECT {src_select} FROM "{table}"').fetchall()
    if not rows:
        return 0, "source empty"

    dst_meta = {c[1]: c for c in dst_cols_info}
    insert_cols = list(dst_cols)
    quoted_cols = ", ".join([f'"{c}"' for c in insert_cols])
    insert_sql = f'INSERT OR REPLACE INTO "{table}" ({quoted_cols}) VALUES ({", ".join(["?"] * len(insert_cols))})'

    common_index = {c: i for i, c in enumerate(common_cols)}
    batch = []
    for row in rows:
        values = []
        for col in insert_cols:
            if col in common_index:
                value = row[common_index[col]]
                # Exact client databases sometimes store NULL in numeric
                # columns which NPPS4 models as NOT NULL.  This is common for
                # accessory material rows whose attribute values are
                # semantically zero.  Normalize only when the target schema
                # requires a value; preserve nullable source NULLs verbatim.
                if value is None and (dst_meta[col][3] or dst_meta[col][5]):
                    value = _value_for_missing_column(dst_meta[col])
                values.append(value)
            else:
                values.append(_value_for_missing_column(dst_meta[col]))
        batch.append(values)

    dst.executemany(insert_sql, batch)
    return len(batch), "copied"


def _insert_defaults(conn: sqlite3.Connection) -> None:
    tables = _source_tables(conn)
    if "game_setting_m" in tables and conn.execute('SELECT COUNT(*) FROM "game_setting_m"').fetchone()[0] == 0:
        cols = _columns(conn, "game_setting_m")
        values = []
        overrides = {
            "game_setting_id": 1,
            "live_loveca_for_energy": 1,
            "live_energy_recoverly_time": 360,
            "live_social_point_for_others": 5,
            "live_social_point_for_friend": 10,
            "live_social_point_for_alliance": 10,
            "live_loveca_for_continue": 1,
            "live_attribute_bonus_rate": 1.1,
            "live_notes_touch_voice_rate": 1.0,
            "live_gameover_card_cnt": 0,
            "live_skill_gauge_cnt": 0,
            "live_skill_need_score": 0,
            "live_other_count": 10,
            "live_other_level_range": 10,
            "live_unclear_love_minus": 0,
            "reward_available_term": 2592000,
            "navigation_replacement_rate": 0,
            "navigation_speak_time": 0,
            "friend_invite_message": "よろしくお願いします。",
            "friend_invite_message_en": "Nice to meet you.",
            "scenario_ending_message": "",
            "scenario_ending_message_en": "",
            "alliance_level_for_making": 0,
            "alliance_game_coin_for_making": 0,
            "deck_max": 18,
            "nextday_time": "00:00:00",
            "card_ranking_cnt": 100,
            "coin_alert_min_value": 0,
            "evolution_attribute_bonus": 1.1,
            "evolution_rankup_coin_rate": 1.0,
            "deck_unit_max": 9,
            "social_point_max": 99999999,
            "sns_coin_max": 99999999,
            "game_coin_max": 999999999,
            "item_max": 9999,
            "initial_game_coin": 0,
            "shop_loveca_for_unit_max": 1,
            "shop_unit_max_gain": 5,
            "unit_max": 1000,
            "waiting_unit_max": 1000,
            "shop_loveca_for_friend_max": 1,
            "shop_friend_max_gain": 5,
            "friend_max": 100,
            "shop_unit_max_limit_cnt": 0,
            "shop_friend_max_limit_cnt": 0,
            "festival_material_max": 9999,
            "klab_id_task_start_date": "2000-01-01 00:00:00",
            "exchange_flag": 1,
        }
        for c in cols:
            values.append(overrides.get(c[1], _value_for_missing_column(c)))
        conn.execute(
            f'INSERT OR REPLACE INTO "game_setting_m" ({", ".join(f"\"{c[1]}\"" for c in cols)}) VALUES ({", ".join("?" for _ in cols)})',
            values,
        )

    if "strings_m" in tables and conn.execute('SELECT COUNT(*) FROM "strings_m"').fetchone()[0] == 0:
        # NPPS4 login bonus uses strings.get("lbonus", 12).
        conn.execute(
            'INSERT OR REPLACE INTO "strings_m" (string_key, string_value, string_label, string_label_en) VALUES (?, ?, ?, ?)',
            ("lbonus", "12", "%d月%d日 登录奖励", "%d/%d Login Bonus"),
        )

    if "unit_attribute_m" in tables and conn.execute('SELECT COUNT(*) FROM "unit_attribute_m"').fetchone()[0] == 0:
        cols = [c[1] for c in _columns(conn, "unit_attribute_m")]
        for row in [(1, "スマイル", "Smile"), (2, "ピュア", "Pure"), (3, "クール", "Cool")]:
            values = []
            for col in cols:
                if col == "unit_attribute_id": values.append(row[0])
                elif col == "name": values.append(row[1])
                elif col == "name_en": values.append(row[2])
                else: values.append(None)
            conn.execute(f'INSERT OR REPLACE INTO "unit_attribute_m" ({", ".join(f"\"{c}\"" for c in cols)}) VALUES ({", ".join("?" for _ in cols)})', values)

    if "add_type_m" in tables and conn.execute('SELECT COUNT(*) FROM "add_type_m"').fetchone()[0] == 0:
        cols = [c[1] for c in _columns(conn, "add_type_m")]
        types = [(0, "なし", "None"), (1000, "アイテム", "Item"), (1001, "部員", "Member"), (1002, "アクセサリー", "Accessory"), (3000, "G", "G"), (3001, "ラブカストーン", "Loveca"), (3002, "友情pt", "Friend Points"), (3006, "シール", "Sticker"), (5000, "ライブ", "Live"), (5100, "称号", "Title"), (5200, "背景", "Background"), (5300, "ストーリー", "Story"), (5500, "スクールアイドルスキル", "SIS"), (8000, "LP回復アイテム", "LP recovery item"), (14000, "思い出", "Memory")]
        for add_type, name, name_en in types:
            values = []
            for col in cols:
                if col == "add_type": values.append(add_type)
                elif col == "name": values.append(name)
                elif col == "name_en": values.append(name_en)
                else: values.append(None)
            conn.execute(f'INSERT OR REPLACE INTO "add_type_m" ({", ".join(f"\"{c}\"" for c in cols)}) VALUES ({", ".join("?" for _ in cols)})', values)



def _ensure_effort_defaults(conn: sqlite3.Connection) -> None:
    """Seed the Live Show reward-box master rows missing from honoka CN main.db.

    honoka-chan's bundled CN assets/main.db does not always contain NPPS4's
    split `effort.db_` table `live_effort_point_box_spec_m`.  NPPS4's login
    bonus path awards login effort points through system/effort.py, so the user
    default box id=1 must be a real master row rather than a missing placeholder.
    These rows mirror the conservative NPPS4 reward-box tiers and are paired
    with npps4/server_data.json's live_effort_drops for ids 1..5.
    """
    tables = _source_tables(conn)
    if "live_effort_point_box_spec_m" not in tables:
        return
    count = conn.execute('SELECT COUNT(*) FROM "live_effort_point_box_spec_m"').fetchone()[0]
    if count > 0:
        return
    cols = [c[1] for c in _columns(conn, "live_effort_point_box_spec_m")]
    tiers = [
        (1, 100000, 100000, 1),
        (2, 400000, 400000, 1),
        (3, 1100000, 1100000, 2),
        (4, 2000000, 2000000, 3),
        (5, 4000000, 4000000, 4),
    ]
    for spec_id, capacity, limited_capacity, num_rewards in tiers:
        values = []
        for col in cols:
            if col == "live_effort_point_box_spec_id": values.append(spec_id)
            elif col == "capacity": values.append(capacity)
            elif col == "limited_capacity": values.append(limited_capacity)
            elif col == "num_rewards": values.append(num_rewards)
            elif col in {"closed_asset", "opened_asset", "box_asset", "login_box_asset"}:
                values.append("assets/image/reward_box/common")
            elif col in {"closed_asset_en", "opened_asset_en", "box_asset_en", "login_box_asset_en", "movie_name_en", "release_tag"}:
                values.append(None)
            elif col == "movie_name": values.append("")
            elif col == "asset_se_id": values.append(0)
            elif col == "_encryption_release_id": values.append(None)
            else: values.append(_value_for_missing_column((0, col, "", 0, None, 0)))
        conn.execute(
            f'INSERT OR REPLACE INTO "live_effort_point_box_spec_m" ({", ".join(f"\"{c}\"" for c in cols)}) VALUES ({", ".join("?" for _ in cols)})',
            values,
        )


def _generated_overlay_version_ok(root: str) -> bool:
    path = os.path.join(root, "achievement.db_")
    if not os.path.isfile(path):
        return False
    try:
        with closing(sqlite3.connect(path)) as conn:
            row = conn.execute(
                f'SELECT value FROM "{MANIFEST_TABLE}" WHERE key = ?', ("generator",)
            ).fetchone()
            full_cols = {r[1] for r in conn.execute('PRAGMA table_info("achievement_m")')}
            return bool(
                row
                and row[0] == GENERATOR_VERSION
                and {"params1", "start_date", "default_open_flag", "auto_reward_flag"}.issubset(full_cols)
                and conn.execute('SELECT COUNT(*) FROM "achievement_m"').fetchone()[0] >= 6000
            )
    except Exception:
        return False


def _generated_effort_db_ok(root: str) -> bool:
    path = os.path.join(root, "effort.db_")
    if not os.path.isfile(path):
        return False
    try:
        with closing(sqlite3.connect(path)) as conn:
            row = conn.execute('SELECT COUNT(*) FROM "live_effort_point_box_spec_m" WHERE live_effort_point_box_spec_id = 1').fetchone()
            return bool(row and row[0] > 0)
    except Exception:
        return False


GENERATOR_VERSION = "cn_honoka_master:v6_accessory_full_cycle"


def _write_manifest(conn: sqlite3.Connection, source: str, db_name: str, copied: list[tuple[str, int, str]]):
    conn.execute(f'CREATE TABLE IF NOT EXISTS "{MANIFEST_TABLE}" (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    conn.execute(f'INSERT OR REPLACE INTO "{MANIFEST_TABLE}" VALUES (?, ?)', ("source", source))
    conn.execute(f'INSERT OR REPLACE INTO "{MANIFEST_TABLE}" VALUES (?, ?)', ("db_name", db_name))
    conn.execute(f'INSERT OR REPLACE INTO "{MANIFEST_TABLE}" VALUES (?, ?)', ("generator", GENERATOR_VERSION))
    for table, count, status in copied:
        conn.execute(f'INSERT OR REPLACE INTO "{MANIFEST_TABLE}" VALUES (?, ?)', (f"table:{table}", f"{count}:{status}"))


def generate_split_db(source_main_db: str, out_dir: str, db_names: Iterable[str] | None = None, overwrite: bool = False) -> dict[str, str]:
    source_main_db = os.path.abspath(source_main_db)
    if not os.path.isfile(source_main_db):
        raise RuntimeError(f"honoka main.db not found: {source_main_db}")

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    db_names = list(db_names or DB_SOURCES.keys())
    result: dict[str, str] = {}

    overlay_path = bundled_cn_client_master_db()
    overlay_exists = os.path.isfile(overlay_path)

    with closing(sqlite3.connect(source_main_db)) as src, closing(
        sqlite3.connect(overlay_path) if overlay_exists else sqlite3.connect(":memory:")
    ) as overlay:
        src_tables = _source_tables(src)
        overlay_tables = _source_tables(overlay) if overlay_exists else set()
        for db_name in db_names:
            if db_name not in DB_SOURCES:
                continue
            target = out_path / f"{db_name}.db_"
            if target.exists() and not overwrite:
                result[db_name] = str(target)
                continue
            if target.exists():
                target.unlink()

            create_sql = _create_sql_by_table(db_name)
            if not create_sql:
                raise RuntimeError(f"No CREATE TABLE SQL extracted for {db_name}")

            copied: list[tuple[str, int, str]] = []
            with closing(sqlite3.connect(str(target))) as dst:
                for table, sql in create_sql.items():
                    dst.execute(sql)
                for table in sorted(create_sql):
                    # Prefer the exact CN 9.7.1 client master when it contains
                    # this table.  Fall back to honoka's broader combined DB for
                    # tables not shipped in the five client master archives.
                    source_conn = overlay if table in overlay_tables else src
                    source_label = "cn_client" if table in overlay_tables else "honoka"
                    source_tables = overlay_tables if table in overlay_tables else src_tables
                    if table in source_tables:
                        try:
                            count, status = _copy_table(source_conn, dst, table)
                            status = f"{source_label}:{status}"
                        except Exception as e:
                            count, status = 0, f"{source_label}:copy_error:{type(e).__name__}:{e}"
                        copied.append((table, count, status))
                    else:
                        copied.append((table, 0, "not_in_cn_client_or_honoka"))
                _insert_defaults(dst)
                _ensure_effort_defaults(dst)
                _write_manifest(dst, source_main_db, db_name, copied)
                dst.commit()
            result[db_name] = str(target)
    return result


def ensure_builtin_split_db(out_dir: str | None = None, overwrite: bool = False) -> str:
    # Import config only after conversion support is loaded; this function is
    # used during normal server startup, not by the offline converter path.
    from npps4.config import config
    out_dir = out_dir or os.path.join(config.get_data_directory(), "db_cn_honoka")
    out_abs = os.path.abspath(out_dir).replace("\\", "/")
    # v4.32 migration: earlier generated CN split DBs copied honoka main.db but
    # left effort.db_ empty because honoka does not ship NPPS4's split
    # live_effort_point_box_spec_m.  Regenerate once when the required default
    # reward-box row is missing; otherwise preserve the user's cached DB files.
    needs_repair = overwrite or not _generated_effort_db_ok(out_abs) or not _generated_overlay_version_ok(out_abs)
    generate_split_db(bundled_honoka_main_db(), out_dir, overwrite=needs_repair)
    return out_abs


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate NPPS4 CN split master DB from honoka main.db")
    parser.add_argument("--source", default=bundled_honoka_main_db())
    parser.add_argument("--out", default="data/db_cn_honoka")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    files = generate_split_db(args.source, args.out, overwrite=args.overwrite)
    for name, path in files.items():
        print(f"{name}: {path}")
