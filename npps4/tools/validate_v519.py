from __future__ import annotations

import ast
import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]
ROOT = PKG.parents[4]


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)
    print("PASS:", message)


def main() -> None:
    build = (PKG / "build_info.py").read_text(encoding="utf-8")
    exchange = (PKG / "system/exchange.py").read_text(encoding="utf-8")
    schema = (PKG / "data/schema.py").read_text(encoding="utf-8")
    server_data = json.loads((PKG / "server_data.json").read_text(encoding="utf-8"))

    for relative in (
        "system/exchange.py",
        "data/schema.py",
        "system/item.py",
        "serialcode/func.py",
        "tools/cn_honoka_master.py",
        "system/profile_projection.py",
        "game/profile.py",
        "system/accessory.py",
        "system/secretbox.py",
    ):
        path = PKG / relative
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    require(True, "modified and inherited critical Python modules parse")

    require("v5.19-clean-config-localization-lp-items" in build, "build marker is v5.19")
    require("exchange_cn_bundled_title_map" not in exchange, "compact old-config title lookup is removed")
    require("exchange_cn_title_map" not in exchange, "active-Master old-config title synthesis is removed")
    require("cn_sticker_shop_names.json" not in exchange, "exchange runtime does not reference the deleted catalogue")
    require("importlib" not in exchange and "import json" not in exchange, "obsolete catalogue-loading imports are gone")
    require(not (PKG / "assets/cn_sticker_shop_names.json").exists(), "obsolete catalogue file is deleted")
    require("Operators who keep a custom configuration remain responsible for its text" in exchange, "runtime ownership of custom configuration is explicit")
    require("name_cn: str | None = None" in schema, "configuration still supports explicit CN names")
    require("no runtime migration" in schema, "schema documents the clean-install policy")

    shop = server_data["sticker_shop"]
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
        supported = supported_by_type.get(int(row["add_type"]))
        if supported is not None and int(row["item_id"]) not in supported:
            continue
        visible_cn.append(row)
    require(len(visible_cn) == 796, "CN catalogue still projects the expected 796 safe rows")
    require(all(isinstance(row.get("name_cn"), str) and row["name_cn"].strip() for row in visible_cn), "every CN-visible row is localized directly in server_data.json")

    recovery = json.loads((PKG / "assets/cn_recovery_items.json").read_text(encoding="utf-8"))
    require(len(recovery) == 52, "all 52 CN LP-recovery items remain bundled")
    serial = (PKG / "serialcode/func.py").read_text(encoding="utf-8")
    require("item_target = 9_999" in serial and "item_ids.update({1, 5})" in serial, "LOVEARROWSHOOT still tops tickets and supported LP items to 9999")

    boxes = {entry.get("id_string"): entry for entry in server_data["secretbox_data"]}
    require(all(key in boxes for key in ("5K", "5L", "5M", "5N")), "all four signed festival pages remain configured")
    require("from . import common" in (PKG / "system/secretbox.py").read_text(encoding="utf-8"), "secretbox startup import fix remains present")

    gradle = ROOT / "app/build.gradle"
    if "Android-Wrapper" in ROOT.name:
        gradle_text = gradle.read_text(encoding="utf-8")
        require("versionCode 519" in gradle_text and "versionName '0.5.19'" in gradle_text, "Android source metadata is v5.19")

    print("All v5.19 clean-configuration checks passed.")


if __name__ == "__main__":
    main()
