from __future__ import annotations

import ast
import base64
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import zipfile

PKG = Path(__file__).resolve().parents[1]
PYROOT = PKG.parent
ROOT = PKG.parents[4]


def require(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)
    print("PASS:", message)


def _load_generator():
    path = PKG / "tools/cn_honoka_master.py"
    spec = importlib.util.spec_from_file_location("validate_v520_cn_generator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read_payload() -> zipfile.ZipFile:
    module = ast.parse((PKG / "tools/android_workspace_payload.py").read_text(encoding="utf-8"))
    encoded = None
    for node in module.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "PAYLOAD_B64"
            for target in node.targets
        ):
            encoded = ast.literal_eval(node.value)
            break
    assert isinstance(encoded, str)
    return zipfile.ZipFile(io.BytesIO(base64.b64decode(encoded)))


def _festival_intersections(db_path: Path, catalogue: dict) -> dict[int, dict[int, int]]:
    with sqlite3.connect(db_path) as conn:
        existing = {
            int(unit_id): int(rarity)
            for unit_id, rarity in conn.execute(
                "SELECT unit_id, rarity FROM unit_m "
                "WHERE disable_rank_up=0 AND rarity IN (4,5)"
            )
        }
    result: dict[int, dict[int, int]] = {}
    for category in (1, 2, 3, 4):
        result[category] = {}
        for rarity in (5, 4):
            candidates = catalogue["thanks_festival_pools"][str(category)][str(rarity)]
            result[category][rarity] = sum(
                existing.get(int(unit_id)) == rarity for unit_id in candidates
            )
    return result


def _write_runtime_stubs(root: Path) -> None:
    crypto = root / "Cryptodome"
    for part in ("", "Cipher", "Hash", "Util", "Signature", "PublicKey", "Protocol"):
        folder = crypto / part
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "__init__.py").write_text("", encoding="utf-8")
    (crypto / "Cipher/AES.py").write_text(
        "MODE_CBC=1\nMODE_CTR=2\nclass Dummy:\n def encrypt(self,x): return x\n def decrypt(self,x): return x\ndef new(*a,**k): return Dummy()\n",
        encoding="utf-8",
    )
    (crypto / "Cipher/PKCS1_v1_5.py").write_text(
        "class Dummy:\n def encrypt(self,x): return x\n def decrypt(self,x,*a): return x\ndef new(*a,**k): return Dummy()\n",
        encoding="utf-8",
    )
    (crypto / "Cipher/DES3.py").write_text(
        "MODE_ECB=1\nclass Dummy:\n def encrypt(self,x): return x\n def decrypt(self,x): return x\ndef new(*a,**k): return Dummy()\n",
        encoding="utf-8",
    )
    (crypto / "Hash/SHA1.py").write_text(
        "class Dummy:\n def update(self,*a): pass\ndef new(*a,**k): return Dummy()\n",
        encoding="utf-8",
    )
    (crypto / "Hash/SHA256.py").write_text("", encoding="utf-8")
    (crypto / "Util/Padding.py").write_text(
        "def pad(x,*a,**k): return x\ndef unpad(x,*a,**k): return x\n",
        encoding="utf-8",
    )
    (crypto / "Signature/pkcs1_15.py").write_text(
        "class Dummy:\n def sign(self,*a): return b''\ndef new(*a,**k): return Dummy()\n",
        encoding="utf-8",
    )
    (crypto / "PublicKey/RSA.py").write_text(
        "class RsaKey:\n n=1\n e=65537\n def publickey(self): return self\ndef import_key(*a,**k): return RsaKey()\n",
        encoding="utf-8",
    )
    (crypto / "Protocol/KDF.py").write_text(
        "def PBKDF2(*a,**k): return b'0'*32\n", encoding="utf-8"
    )
    (root / "aiosqlite.py").write_text(
        "import sqlite3\n"
        "DatabaseError=sqlite3.DatabaseError\nError=sqlite3.Error\n"
        "IntegrityError=sqlite3.IntegrityError\nNotSupportedError=sqlite3.NotSupportedError\n"
        "OperationalError=sqlite3.OperationalError\nProgrammingError=sqlite3.ProgrammingError\n"
        "sqlite_version=sqlite3.sqlite_version\nsqlite_version_info=sqlite3.sqlite_version_info\n"
        "class Connection: pass\ndef connect(*a,**k): return Connection()\n",
        encoding="utf-8",
    )
    (root / "honkypy.py").write_text(
        "class Dummy:\n def encrypt(self,x): return x\ndef encrypt_setup_by_gametype(*a,**k): return Dummy()\n",
        encoding="utf-8",
    )


def _runtime_smoke() -> None:
    with tempfile.TemporaryDirectory(prefix="npps4-v520-import-") as temp:
        temp_path = Path(temp)
        stubs = temp_path / "stubs"
        _write_runtime_stubs(stubs)
        config_path = temp_path / "config.toml"
        config_path.write_text(
            "[download]\ndefault_profile='cn'\n\n"
            "[download.profiles.cn]\nenabled=true\nbackend='none'\n\n"
            "[download.profiles.cn.none]\nclient_version='97.4.6'\n",
            encoding="utf-8",
        )
        code = r'''
import asyncio
from types import SimpleNamespace
from npps4 import client_profile
from npps4.system import accessory, client_catalogue, costume, item, profile_projection, secretbox
import npps4.serialcode.func
import npps4.game.friend
import npps4.game.profile
import npps4.game.live
import npps4.system.advanced

class Context:
    def __init__(self, profile):
        self.profile=profile
        self._cache={}
        self.db=SimpleNamespace()
    def get_cache(self,key,identifier): return self._cache.get((key,identifier))
    def set_cache(self,key,identifier,value): self._cache[(key,identifier)]=value

class Rows:
    def __init__(self, values): self.values=values
    def all(self): return self.values
    def scalars(self): return self.values

async def main():
    for profile in (client_profile.ClientProfile.CN, client_profile.ClientProfile.GL):
        ctx=Context(profile)
        catalogue=await client_catalogue.current(ctx)
        configured=catalogue.thanks_festival_pools
        class UnitSession:
            async def execute(self, query):
                values=[]
                for rarity in (5,4):
                    for unit_id in configured[2][rarity] + configured[4][rarity]:
                        values.append(SimpleNamespace(unit_id=unit_id, rarity=rarity))
                return Rows(values)
        ctx.db.unit=UnitSession()
        aqours=await secretbox._thanks_festival_pools(ctx,2)
        liella=await secretbox._thanks_festival_pools(ctx,4)
        assert all(aqours) and all(liella), (profile, [len(x) for x in aqours], [len(x) for x in liella])
        pairs=dict(catalogue.special_accessory_pairs)
        first_accessory=next(iter(pairs))
        assert await accessory._special_target_unit_id(ctx, first_accessory) == pairs[first_accessory]
        async def no_table(*args): return False
        old=accessory._unit_db_table_exists
        accessory._unit_db_table_exists=no_table
        try:
            fallback=await accessory.accessory_master_by_id(ctx, first_accessory)
            assert fallback and fallback['accessory_id']==first_accessory
        finally:
            accessory._unit_db_table_exists=old
        class ItemSession:
            async def get(self,*args): return None
        ctx.db.item=ItemSession()
        recovery_id=next(iter(catalogue.recovery_item_ids))
        contract=await item.get_recovery_item_info(ctx,recovery_id)
        assert contract and contract.recovery_item_id==recovery_id

    # Cross-profile role fallback: unsupported primary card keeps its character,
    # never substitutes the explicitly excluded other social role.
    ctx=Context(client_profile.ClientProfile.CN)
    cn=await client_catalogue.current(ctx)
    gl=await client_catalogue.for_context(ctx,'gl')
    known=await client_catalogue.known_unit_type_by_id(ctx,'cn')
    primary_unit=same_unit=None
    for unit_id in sorted(gl.unit_ids-cn.unit_ids):
        unit_type=known.get(unit_id)
        if unit_type is None: continue
        same=next((candidate for candidate in cn.unit_ids if known.get(candidate)==unit_type),None)
        if same is not None:
            primary_unit,same_unit=unit_id,same
            break
    assert primary_unit is not None and same_unit is not None
    other_unit=next(unit_id for unit_id in cn.unit_ids if known.get(unit_id)!=known.get(same_unit))
    primary=SimpleNamespace(id=10,user_id=1,active=True,favorite_flag=False,love=0,unit_id=primary_unit)
    excluded=SimpleNamespace(id=20,user_id=1,active=True,favorite_flag=True,love=999,unit_id=same_unit)
    same=SimpleNamespace(id=30,user_id=1,active=True,favorite_flag=False,love=10,unit_id=same_unit)
    other=SimpleNamespace(id=40,user_id=1,active=True,favorite_flag=False,love=1,unit_id=other_unit)
    class MainSession:
        async def get(self, cls, owning_id): return {10:primary,20:excluded,30:same,40:other}.get(owning_id)
        async def execute(self, query): return Rows([excluded,same,other])
    ctx.db.main=MainSession()
    old_owned=profile_projection.owned_unit
    async def projected(context, owned):
        if owned.id==10: return None
        return (owned,SimpleNamespace(default_leader_skill_id=0),SimpleNamespace(),SimpleNamespace())
    profile_projection.owned_unit=projected
    try:
        result=await profile_projection._role_projection(ctx,SimpleNamespace(id=1),10,excluded_owning_ids=(20,))
        assert result and result[0].id==30, result
    finally:
        profile_projection.owned_unit=old_owned

    selected=SimpleNamespace(id=777)
    projection=(selected,object(),object(),object())
    old_social=costume.social_appearance_for_owned_unit
    seen=[]
    async def social(context, owned, native_fallback=True):
        seen.append(owned.id); return 'ok'
    costume.social_appearance_for_owned_unit=social
    try:
        assert await profile_projection.social_costume(ctx,SimpleNamespace(),projection)=='ok'
        assert seen==[777]
    finally:
        costume.social_appearance_for_owned_unit=old_social

asyncio.run(main())
print('RUNTIME_SMOKE_OK')
'''
        env = dict(os.environ)
        env.update(
            NPPS4_CONFIG=str(config_path),
            NPPS4_ROOT_DIR=str(PYROOT),
            PYTHONPATH=os.pathsep.join((str(stubs), str(PYROOT))),
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            text=True,
            capture_output=True,
            timeout=120,
        )
        if result.returncode != 0:
            raise AssertionError(
                "runtime import/contract smoke failed:\n" + result.stdout + result.stderr
            )
        require("RUNTIME_SMOKE_OK" in result.stdout, "critical modules import and profile contracts execute")


def main() -> None:
    critical = (
        "build_info.py",
        "system/client_catalogue.py",
        "system/profile_projection.py",
        "system/secretbox.py",
        "system/item.py",
        "system/accessory.py",
        "system/exchange.py",
        "serialcode/func.py",
        "game/friend.py",
        "game/profile.py",
        "tools/cn_honoka_master.py",
        "tools/android_workspace_payload.py",
    )
    for relative in critical:
        path = PKG / relative
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    require(True, "all v5.20 critical Python modules parse")

    build = (PKG / "build_info.py").read_text(encoding="utf-8")
    require("v5.20-role-profile-master-contract-fix" in build, "build marker is v5.20")

    server_data_bytes = (PKG / "server_data.json").read_bytes()
    server_data = json.loads(server_data_bytes)
    boxes = {entry.get("id_string"): entry for entry in server_data["secretbox_data"]}
    expected_categories = {"5K": 1, "5L": 2, "5M": 3, "5N": 4}
    require(
        all(boxes[key].get("member_category") == category for key, category in expected_categories.items()),
        "four signed festival pages map to μ's/Aqours/Nijigasaki/Liella categories",
    )
    require(boxes["5L"]["name"].find("Aqours") >= 0, "Aqours signed page is configured")
    require(boxes["5N"]["name"].find("Liella") >= 0, "Liella signed page is configured")

    catalogues: dict[str, dict] = {}
    for profile, expected_units, expected_accessories, expected_special, expected_recovery in (
        ("cn", 3644, 336, 258, 52),
        ("gl", 3998, 562, 484, 47),
    ):
        catalogue = json.loads((PKG / f"assets/client_catalogue/{profile}.json").read_text(encoding="utf-8"))
        catalogues[profile] = catalogue
        require(len(catalogue["unit_ids"]) == expected_units, f"{profile.upper()} exact unit catalogue count")
        require(len(catalogue["accessory_ids"]) == expected_accessories, f"{profile.upper()} exact accessory catalogue count")
        require(len(catalogue["special_accessory_pairs"]) == expected_special, f"{profile.upper()} dedicated-accessory mapping count")
        require(len(catalogue["recovery_item_ids"]) == expected_recovery, f"{profile.upper()} LP-item catalogue count")
        pairs = {(int(a), int(u)) for a, u in catalogue["special_accessory_pairs"]}
        require(len(pairs) == expected_special, f"{profile.upper()} dedicated-accessory mappings are unique")
        require(
            {a for a, _ in pairs} <= set(map(int, catalogue["accessory_ids"])),
            f"{profile.upper()} every dedicated accessory exists in the exact client catalogue",
        )
        require(
            {u for _, u in pairs} <= set(map(int, catalogue["unit_ids"])),
            f"{profile.upper()} every dedicated target card exists in the exact client catalogue",
        )
        for category in (1, 2, 3, 4):
            for rarity in (5, 4):
                require(
                    bool(catalogue["thanks_festival_pools"][str(category)][str(rarity)]),
                    f"{profile.upper()} festival category {category} rarity {rarity} has candidates",
                )

    generator = _load_generator()
    require(
        generator.GENERATOR_VERSION == "cn_honoka_master:v8_profile_contracts",
        "CN generated Master cache version is bumped",
    )
    with tempfile.TemporaryDirectory(prefix="npps4-v520-cn-master-") as temp:
        generated = generator.generate_split_db(
            str(PKG / "assets/honoka_main.db"), temp, db_names=["unit", "item"], overwrite=True
        )
        cn_counts = _festival_intersections(Path(generated["unit"]), catalogues["cn"])
        with sqlite3.connect(generated["unit"]) as conn:
            accessory_count = conn.execute("SELECT COUNT(*) FROM accessory_m").fetchone()[0]
            special_count = conn.execute("SELECT COUNT(*) FROM accessory_special_m").fetchone()[0]
        with sqlite3.connect(generated["item"]) as conn:
            recovery_count = conn.execute("SELECT COUNT(*) FROM recovery_item_m").fetchone()[0]
        require(accessory_count == 336 and special_count == 258, "generated CN unit Master has exact accessory contracts")
        require(recovery_count == 52, "generated CN item Master has all 52 LP items")
    gl_counts = _festival_intersections(PKG / "assets/honoka_main.db", catalogues["gl"])
    for profile, counts in (("CN", cn_counts), ("GL", gl_counts)):
        require(all(counts[2][rarity] > 0 for rarity in (5, 4)), f"{profile} Aqours page survives active-Unit intersection")
        require(all(counts[4][rarity] > 0 for rarity in (5, 4)), f"{profile} Liella page survives active-Unit intersection")
        require(all(counts[3][rarity] > 0 for rarity in (5, 4)), f"{profile} Nijigasaki page remains visible")

    known_map = json.loads((PKG / "assets/known_unit_type_by_id.json").read_text(encoding="utf-8"))
    require(len(known_map) >= 3998, "cross-profile role fallback has a union unit-to-character map")

    projection = (PKG / "system/profile_projection.py").read_text(encoding="utf-8")
    friend = (PKG / "game/friend.py").read_text(encoding="utf-8")
    profile = (PKG / "game/profile.py").read_text(encoding="utf-8")
    live = (PKG / "system/advanced.py").read_text(encoding="utf-8")
    require("excluded_owning_ids=(lead_id,)" in projection, "navigator fallback excludes the main-deck lead")
    require("excluded_owning_ids=(partner_id,)" in projection, "lead fallback excludes the navigator")
    require("known_unit_type_by_id" in projection, "cross-profile fallback prefers the same character")
    require("navigation_unit(context, target_user)" in friend, "friend list/search uses the navigation partner")
    require("main_deck_center_unit" in profile and "navigation_unit" in profile, "profile lead and navigator are generated independently")
    require("live_guest_center_unit" in live, "Live guest path retains the dedicated lead projection")
    require("fallback_projection[0]" in projection, "costume remains bound to the exact projected owned card")

    exchange = (PKG / "system/exchange.py").read_text(encoding="utf-8")
    require(
        "context.profile is client_profile.ClientProfile.CN" in exchange,
        "CN sticker-shop names are selected by client profile rather than language",
    )
    visible_cn = [
        row for row in server_data["sticker_shop"]
        if (row.get("profiles") is None or "cn" in row["profiles"])
        and isinstance(row.get("name_cn"), str) and row["name_cn"].strip()
    ]
    require(len(visible_cn) >= 796, "bundled CN shop configuration carries localized names")

    cn_recovery = json.loads((PKG / "assets/cn_recovery_items.json").read_text(encoding="utf-8"))
    gl_recovery = json.loads((PKG / "assets/gl_recovery_items.json").read_text(encoding="utf-8"))
    require(len(cn_recovery) == 52 and len(gl_recovery) == 47, "profile recovery contracts contain 52 CN / 47 GL rows")
    require(
        {int(row["recovery_item_id"]) for row in cn_recovery} - {int(row["recovery_item_id"]) for row in gl_recovery}
        == {801, 802, 803, 804, 805},
        "the five CN-only LP items are not projected into GL",
    )
    serial = (PKG / "serialcode/func.py").read_text(encoding="utf-8")
    require("item_ids.update({1, 5})" in serial, "LOVEARROWSHOOT explicitly includes ordinary and blue scouting tickets")
    require("target_count: int = 3" in serial, "dedicated-accessory testing preserves two materials plus one equip copy")
    require("LP recovery top-up verification failed" in serial, "LP-item top-up verifies the committed inventory")
    require("catalogue.special_target_unit_ids" in serial, "test-card copies use exact client dedicated-accessory targets")

    payload = _read_payload()
    require(payload.read("npps4/server_data.json") == server_data_bytes, "Android first-run payload embeds the exact current server_data.json")
    require(
        payload.read("npps4/server_data_schema.json") == (PKG / "server_data_schema.json").read_bytes(),
        "Android first-run payload embeds the exact current schema",
    )
    embedded = json.loads(payload.read("npps4/server_data.json"))
    require(
        sum("name_cn" in row for row in embedded["sticker_shop"]) == 804,
        "clean Android installation receives all 804 name_cn fields",
    )
    embedded_boxes = {entry.get("id_string") for entry in embedded["secretbox_data"]}
    require({"5K", "5L", "5M", "5N"} <= embedded_boxes, "clean Android installation receives all four festival pages")

    _runtime_smoke()

    gradle = ROOT / "app/build.gradle"
    if "Android-Wrapper" in ROOT.name:
        gradle_text = gradle.read_text(encoding="utf-8")
        require("versionCode 520" in gradle_text, "Android versionCode is 520")
        require("versionName '0.5.20'" in gradle_text or 'versionName "0.5.20"' in gradle_text, "Android versionName is 0.5.20")

    print("All v5.20 role/profile/Master-contract checks passed.")


if __name__ == "__main__":
    main()
