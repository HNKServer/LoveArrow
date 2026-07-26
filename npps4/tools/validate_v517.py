from __future__ import annotations

import ast
import json
from pathlib import Path

PKG = Path(__file__).resolve().parents[1]


def java_hash(text: str) -> int:
    value = 0
    for ch in text:
        value = (31 * value + ord(ch)) & 0xFFFFFFFF
    return value - 0x100000000 if value & 0x80000000 else value


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)
    print("PASS:", message)


def main() -> None:
    profile_projection = (PKG / "system/profile_projection.py").read_text(encoding="utf-8")
    profile = (PKG / "game/profile.py").read_text(encoding="utf-8")
    accessory = (PKG / "system/accessory.py").read_text(encoding="utf-8")
    serial = (PKG / "serialcode/func.py").read_text(encoding="utf-8")
    build = (PKG / "build_info.py").read_text(encoding="utf-8")
    data = json.loads((PKG / "server_data.json").read_text(encoding="utf-8"))

    for path in [PKG / "system/profile_projection.py", PKG / "game/profile.py", PKG / "system/accessory.py", PKG / "serialcode/func.py", PKG / "system/secretbox.py"]:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    require(True, "modified Python modules parse as valid AST")

    social = profile_projection[profile_projection.index("async def social_costume"):profile_projection.index("async def _live_leader_supported")]
    require("fallback_projection[0]" in social, "social costume is bound to the exact projected owned card")
    require("center_unit_owning_user_id" not in social, "social costume does not substitute the navigation partner")
    require("center_costume" in profile and "partner_costume" in profile, "profile computes center and navigator appearances separately")
    require("display_costume=center_costume" in profile and "display_costume=partner_costume" in profile, "profile serializes each appearance into its matching card")

    require("len(ids) != 2" in accessory, "accessory creation requires two owned cards")
    require("units[0].unit_id) == int(units[1].unit_id" in accessory, "dedicated accessory path requires two copies of the same card")
    require("return any(amount >= 2 for amount in eligible_by_unit.values())" in accessory, "dedicated accessory availability requires two eligible copies")
    require("target_count: int = 3" in serial, "test code keeps three eligible mapped UR copies")
    require("two are consumed" in serial and "third remains" in serial, "test stock documents two consumed plus one wearable copy")
    require("user.unit_max = max(user.unit_max, 10_000)" in serial, "test code expands member capacity before bulk grants")

    boxes = {entry.get("id_string"): entry for entry in data["secretbox_data"]}
    for key, expected in (("5K",1718),("5L",1719),("5M",1720),("5N",1721)):
        require(key in boxes, f"thank-you festival page {key} exists")
        require(java_hash(key) == expected, f"{key} hashes to official page ID {expected}")
        require(set(boxes[key].get("profiles", [])) == {"cn","gl"}, f"{key} is available to both CN and GL")
        require(len(boxes[key].get("buttons", [])) == 3, f"{key} keeps all three official draw buttons")

    small = [entry for entry in data["sticker_shop"] if entry.get("name_en") == "Small Happiness"]
    require(len(small) == 1 and small[0].get("profiles") == ["gl"], "Small Happiness stays limited to the supplied GL catalogue")
    require(
        "v5.17-social-costume-festival-special-accessory-fix" in build
        or "v5.18-cn-shop-localization-lp-items" in build
        or "v5.19-clean-config-localization-lp-items" in build
        or "v5.20-role-profile-master-contract-fix" in build,
        "build is v5.17 or an explicitly inheriting v5.18/v5.19/v5.20 release",
    )
    require("from . import common" in (PKG / "system/secretbox.py").read_text(encoding="utf-8"), "secretbox startup import regression remains fixed")

    print("All v5.17 contract checks passed.")


if __name__ == "__main__":
    main()
