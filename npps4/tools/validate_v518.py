from __future__ import annotations

import ast
import importlib.util
import json
import sqlite3
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
ROOT = PKG.parents[4]


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)
    print("PASS:", message)


def load_cn_generator():
    path = PKG / "tools/cn_honoka_master.py"
    spec = importlib.util.spec_from_file_location("validate_v518_cn_generator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    build = (PKG / "build_info.py").read_text(encoding="utf-8")
    schema = (PKG / "data/schema.py").read_text(encoding="utf-8")
    exchange = (PKG / "system/exchange.py").read_text(encoding="utf-8")
    item = (PKG / "system/item.py").read_text(encoding="utf-8")
    serial = (PKG / "serialcode/func.py").read_text(encoding="utf-8")
    generator = (PKG / "tools/cn_honoka_master.py").read_text(encoding="utf-8")
    profile_projection = (PKG / "system/profile_projection.py").read_text(encoding="utf-8")
    profile = (PKG / "game/profile.py").read_text(encoding="utf-8")
    accessory = (PKG / "system/accessory.py").read_text(encoding="utf-8")
    secretbox = (PKG / "system/secretbox.py").read_text(encoding="utf-8")
    server_data = json.loads((PKG / "server_data.json").read_text(encoding="utf-8"))

    modified = [
        PKG / "data/schema.py",
        PKG / "system/exchange.py",
        PKG / "system/item.py",
        PKG / "serialcode/func.py",
        PKG / "tools/cn_honoka_master.py",
        PKG / "system/profile_projection.py",
        PKG / "game/profile.py",
        PKG / "system/accessory.py",
        PKG / "system/secretbox.py",
    ]
    for path in modified:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    require(True, "modified and preserved critical Python modules parse as valid AST")

    is_v519 = "v5.19-clean-config-localization-lp-items" in build
    require("v5.18-cn-shop-localization-lp-items" in build or is_v519, "build marker is v5.18 or inheriting v5.19")
    require("name_cn: str | None = None" in schema, "sticker-shop schema accepts explicit CN names")
    if is_v519:
        require("exchange_cn_bundled_title_map" not in exchange and "exchange_cn_title_map" not in exchange, "v5.19 removes old-workspace title fallbacks")
        require("cn_sticker_shop_names.json" not in exchange, "v5.19 has no runtime compact-name catalogue")
        require("raw_info.name_cn.strip()" in exchange, "CN titles come directly from server_data.json")
        require(not (PKG / "assets/cn_sticker_shop_names.json").exists(), "obsolete compact-name asset is absent")
    else:
        require("exchange_cn_bundled_title_map" in exchange and "exchange_cn_title_map" in exchange, "old workspace configs have bundled-name and active-Master fallbacks")
        require("BasicSchoolIdolContext.cache" in exchange and "discarded with" in exchange, "title fallbacks document request-local cache lifetime")
        require("sqlalchemy.select(model).where(column.in_(sorted(ids)))" in exchange, "old-config fallback batches only missing Master IDs")
        require("raw_info.name_cn.strip()" in exchange, "bundled CN names avoid Master queries")

    shop = server_data["sticker_shop"]
    named = [row for row in shop if isinstance(row.get("name_cn"), str) and row["name_cn"].strip()]
    require(len(named) >= 800, "bundled sticker shop carries CN/localized names for at least 800 rows")
    catalogue = json.loads((PKG / "assets/client_catalogue/cn.json").read_text(encoding="utf-8"))
    supported_by_type = {
        1000: set(catalogue["item_ids"]),
        5100: set(catalogue["award_ids"]),
        5200: set(catalogue["background_ids"]),
        14000: set(catalogue["museum_ids"]),
    }
    exchange_points = set(catalogue["exchange_point_ids"])
    visible_cn = []
    for row in shop:
        if row.get("profiles") is not None and "cn" not in row["profiles"]:
            continue
        if any(int(cost["rarity"]) not in exchange_points for cost in row["costs"]):
            continue
        add_type = int(row["add_type"])
        if add_type in supported_by_type and int(row["item_id"]) not in supported_by_type[add_type]:
            continue
        visible_cn.append(row)
    require(len(visible_cn) == 796, "exact CN catalogue projects 796 safe sticker-shop rows")
    require(all(isinstance(row.get("name_cn"), str) and row["name_cn"].strip() for row in visible_cn), "every CN-visible shop row has an explicit localized title")
    blue = [row for row in shop if int(row["add_type"]) == 1000 and int(row["item_id"]) == 5]
    require(len(blue) == 1 and blue[0].get("name_cn") == "辅助招募券", "item 5 uses the official CN Master name")

    if not is_v519:
        bundled_names = json.loads((PKG / "assets/cn_sticker_shop_names.json").read_text(encoding="utf-8"))
        require(len(bundled_names) >= 790, "old workspaces receive the compact bundled CN sticker-name map")
        require(bundled_names.get("1000:5") == "辅助招募券", "bundled old-workspace map includes item 5 CN name")

    honoka_db = PKG / "assets/honoka_main.db"
    with sqlite3.connect(honoka_db) as conn:
        samples = {
            (5100, 1): conn.execute("SELECT name_en FROM award_m WHERE award_id=1").fetchone()[0],
            (5200, 100): conn.execute("SELECT name_en FROM background_m WHERE background_id=100").fetchone()[0],
            (3006, 2): conn.execute("SELECT name_en FROM exchange_point_m WHERE exchange_point_id=2").fetchone()[0],
        }
    index = {(int(row["add_type"]), int(row["item_id"])): row for row in shop}
    for key, official in samples.items():
        require(index[key].get("name_cn") == official, f"shop row {key} matches the existing CN catalogue label")

    recovery_json = PKG / "assets/cn_recovery_items.json"
    recovery_rows = json.loads(recovery_json.read_text(encoding="utf-8"))
    expected_ids = set(range(1, 28)) | {801, 802, 803, 804, 805, 995, 777001, 777002, 777003} | set(range(777005, 777021))
    actual_ids = {int(row["recovery_item_id"]) for row in recovery_rows}
    require(len(recovery_rows) == 52, "bundled CN LP-recovery catalogue contains 52 exact rows")
    require(actual_ids == expected_ids, "CN LP-recovery IDs exactly match honoka/client catalogue")
    require({int(row["recovery_type"]) for row in recovery_rows} <= {1, 2}, "all recovery rows use supported percentage/fixed semantics")
    by_id = {int(row["recovery_item_id"]): row for row in recovery_rows}
    require(by_id[1]["name_en"] == "方糖[耐力50]" and int(by_id[1]["recovery_value"]) == 50, "Sugar Cube CN name and fixed recovery value are preserved")
    require(by_id[3]["name_en"] == "糖罐[耐力100%]" and int(by_id[3]["recovery_type"]) == 1, "Sugar Pot CN percentage semantics are preserved")

    require('GENERATOR_VERSION = "cn_honoka_master:v7_recovery_items"' in generator, "CN split-Master cache version forces regeneration")
    require("_seed_cn_recovery_items(dst)" in generator, "CN item DB generation seeds recovery-item Master rows")
    require("bundled_cn_recovery_items" in generator, "generated DB manifest identifies bundled recovery rows")

    # Execute the stdlib-only generator against a temporary output and inspect
    # the actual generated SQLite table, not only source strings.
    module = load_cn_generator()
    with tempfile.TemporaryDirectory(prefix="npps4-v518-") as temp:
        generated = module.generate_split_db(
            str(PKG / "assets/honoka_main.db"), temp, db_names=["item"], overwrite=True
        )
        with sqlite3.connect(generated["item"]) as conn:
            count = conn.execute("SELECT COUNT(*) FROM recovery_item_m").fetchone()[0]
            sugar = conn.execute(
                "SELECT name_en, recovery_type, recovery_value FROM recovery_item_m WHERE recovery_item_id=1"
            ).fetchone()
            manifest = conn.execute(
                'SELECT value FROM "_npps4_cn_honoka_manifest" WHERE key="table:recovery_item_m"'
            ).fetchone()[0]
        require(count == 52, "actual generated CN item.db_ contains 52 LP items")
        require(sugar == ("方糖[耐力50]", 2, 50), "actual generated CN item.db_ preserves official item data")
        require(manifest == "52:bundled_cn_recovery_items", "generated DB manifest records the recovery source")

    require("get_supported_recovery_item_ids" in item, "active-profile recovery capability helper exists")
    require("main.RecoveryItem.item_id.in_(sorted(supported))" in item, "shared recovery inventory is filtered before serialization")
    require("context.profile.value" in item, "recovery capability cache is keyed by active profile")
    require("await item.get_supported_recovery_item_ids" in serial, "test code grants only active-client recovery items")
    require("item_target = 9_999" in serial, "test resource target remains 9999")
    require("item_ids.update({1, 5})" in serial, "LOVEARROWSHOOT explicitly includes normal ticket and item 5")

    # Preserve the v5.17 contracts which this release must not regress.
    social = profile_projection[
        profile_projection.index("async def social_costume") : profile_projection.index("async def _live_leader_supported")
    ]
    require("fallback_projection[0]" in social and "center_unit_owning_user_id" not in social, "friend costume remains bound to the projected card")
    require("display_costume=center_costume" in profile and "display_costume=partner_costume" in profile, "singer and navigator costumes remain separate")
    require("len(ids) != 2" in accessory, "dedicated accessory creation still consumes two cards")
    require("target_count: int = 3" in serial, "test code still keeps three dedicated-accessory copies")
    boxes = {entry.get("id_string"): entry for entry in server_data["secretbox_data"]}
    require(all(key in boxes for key in ("5K", "5L", "5M", "5N")), "all four festival signed pages remain configured")
    require("from . import common" in secretbox, "secretbox startup import fix remains present")

    schema_json = json.loads((PKG / "server_data_schema.json").read_text(encoding="utf-8"))
    sticker_props = schema_json["$defs"]["StickerShop"]["properties"]
    require("name_cn" in sticker_props and "profiles" in sticker_props, "JSON schema documents CN names and profile visibility")

    print("All v5.18/v5.19 inherited contract checks passed.")


if __name__ == "__main__":
    main()
