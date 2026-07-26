"""Android-side control surface for NPPS4.

This module is called from the Kotlin wrapper through Chaquopy.  It keeps all
mutable files in an app-private workspace, then starts the bundled NPPS4 server
with NPPS4_ROOT_DIR and NPPS4_CONFIG pointing to that workspace.
"""

from __future__ import annotations

# Native Pydantic v2 build: no local compatibility shim is imported here.
# If pydantic-core is missing, the Gradle build must fail rather than letting
# runtime imports degrade into partial v1/v2 emulation.

import base64
import io
import json
import os
import re
import sys
import importlib.resources as resources
import shutil
import socket
import sqlite3
import threading
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any

BUNDLE_ROOT = Path(__file__).resolve().parent
_state_lock = threading.RLock()
_state: dict[str, Any] = {
    "phase": "stopped",
    "running": False,
    "last_error": "",
    "host": "127.0.0.1",
    "port": 51376,
    "started_at": 0.0,
    "thread_alive": False,
}
_server_thread: threading.Thread | None = None



def _copy_resource_tree(package: str, dst: Path, overwrite: bool = False) -> None:
    """Copy a Python package resource tree to a real filesystem path.

    Chaquopy exposes bundled Python files through an AssetFinder. Many modules
    can be imported from there, but Alembic requires env.py and version scripts
    to exist as normal files. Export them into the app workspace.
    """
    try:
        root = resources.files(package)
    except Exception:
        return
    dst.mkdir(parents=True, exist_ok=True)

    def rec(node, out: Path) -> None:
        if node.is_dir():
            out.mkdir(parents=True, exist_ok=True)
            for child in node.iterdir():
                rec(child, out / child.name)
        else:
            if out.exists() and not overwrite:
                return
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                out.write_bytes(node.read_bytes())
            except Exception:
                pass

    rec(root, dst)



def _extract_embedded_workspace_defaults(root: Path, overwrite: bool = False) -> None:
    """Extract first-run editable defaults without relying on AssetFinder paths.

    The payload is an imported Python module, so Chaquopy always packages it. Files
    are written only when absent, preserving user edits and deletions of individual
    configuration entries inside existing files.
    """
    try:
        from npps4.tools.android_workspace_payload import PAYLOAD_B64
    except Exception:
        return
    try:
        data = base64.b64decode(PAYLOAD_B64)
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                out = root / info.filename
                if out.exists() and not overwrite:
                    continue
                out.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, out.open("wb") as fh:
                    shutil.copyfileobj(src, fh)
    except Exception:
        # Keep an upgrade with an already-populated workspace startable even if
        # the embedded payload itself is damaged. Later validation will report
        # any genuinely missing required hook.
        return


def _extract_embedded_alembic(dst: Path, overwrite: bool = True) -> None:
    """Extract bundled Alembic files from an embedded base64 zip.

    This is the Android-safe fallback. It does not rely on pathlib/open() over
    Chaquopy's AssetFinder path, and it does not rely on importlib.resources
    being able to iterate package trees.
    """
    try:
        from npps4.tools.android_alembic_payload import PAYLOAD_B64
    except Exception:
        return
    dst.mkdir(parents=True, exist_ok=True)
    data = base64.b64decode(PAYLOAD_B64)
    with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            out = dst / info.filename
            if out.exists() and not overwrite:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info, "r") as src, out.open("wb") as fh:
                shutil.copyfileobj(src, fh)

_NPPS4_DEFAULT_KEY_SHA256 = "a7f25afeace3b5ad0dcf50d2d605f484a9dc658932ff05d5f9c0060c572b6a77"
_HONOKA_KEY_SHA256 = "fb0f2e77e54b41c8ab3ada59500c90ef10fb5ac8756a40f777c72dc8e76eac47"


def _sha256_file(path: Path) -> str | None:
    try:
        import hashlib
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def _copy_if_missing(src: Path, dst: Path) -> bool:
    """Copy a filesystem-backed bundled file only when the destination is absent.

    Chaquopy may expose Python modules through AssetFinder pseudo-paths which look
    like normal paths but cannot be opened by shutil. Missing/non-filesystem bundle
    paths must therefore be non-fatal; critical first-run defaults are supplied by
    the embedded workspace payload below.
    """
    if dst.exists():
        return True
    try:
        if not src.exists():
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return True
    except (FileNotFoundError, OSError):
        return False



def _zip_has_root_server_info(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            names = {name.replace("\\", "/") for name in zf.namelist()}
        return "server_info.json" in names
    except Exception:
        return False


def _copy_cn_server_info_override(src: Path, dst: Path) -> None:
    """Install/migrate the bundled CN server_info override.

    v4.19-v4.23 could leave a workspace copy containing only
    config/server_info.json.  CN 99 update archives expect root server_info.json,
    so overwrite that specific broken copy while preserving a user-supplied
    root-level override.
    """
    if not src.exists():
        return
    if dst.exists() and _zip_has_root_server_info(dst):
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _copy_key_if_missing(src: Path, dst: Path) -> None:
    if src.exists() and not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _merge_copy_tree(src: Path, dst: Path, overwrite: bool = False) -> None:
    """Merge-copy a bundled directory into the mutable Android workspace.

    Unlike _copy_if_missing, this still populates a directory which already
    exists but is empty.  That matters for templates/static: the Kotlin side
    creates root/templates and root/static before Python starts, so a simple
    copytree-if-missing silently left them empty and Jinja later failed with
    TemplateNotFound('error.html').
    """
    if not src.exists() or not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for child in src.iterdir():
        out = dst / child.name
        if child.is_dir():
            _merge_copy_tree(child, out, overwrite=overwrite)
        else:
            if out.exists() and not overwrite:
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(child, out)
            except Exception:
                # Keep server startup resilient. app.py also has a bundled
                # template fallback, so a copy failure shouldn't be fatal.
                pass


def _install_server_keys(root: Path) -> None:
    """Install both NPPS4/GL and honoka/CN RSA keys into the workspace.

    v4.13 solved CN by replacing default_server_key.pem with honoka-chan's
    private key, but that would make GL/JP clients patched for NPPS4's default
    key fail.  Keep default_server_key.pem as the NPPS4 key and add
    honoka_server_key.pem as a fallback key; Python will auto-detect which key
    can decrypt /login/authkey's dummy_token and will sign later responses with
    the same key.
    """
    root.mkdir(parents=True, exist_ok=True)
    npps4_src = BUNDLE_ROOT / "npps4_default_server_key.pem"
    if not npps4_src.exists():
        npps4_src = BUNDLE_ROOT / "default_server_key.pem"
    honoka_src = BUNDLE_ROOT / "honoka_server_key.pem"

    _copy_key_if_missing(npps4_src, root / "npps4_default_server_key.pem")
    _copy_key_if_missing(honoka_src, root / "honoka_server_key.pem")

    default_dst = root / "default_server_key.pem"
    if not default_dst.exists():
        _copy_key_if_missing(npps4_src, default_dst)
        return

    digest = _sha256_file(default_dst)
    if digest == _HONOKA_KEY_SHA256 and npps4_src.exists():
        # Migrate v4.13 workspaces back to NPPS4 as the primary key, but keep
        # the honoka key separately so the CN client still works.
        backup = default_dst.with_suffix(default_dst.suffix + ".honoka-default.bak")
        try:
            if not backup.exists():
                shutil.copy2(default_dst, backup)
        except Exception:
            pass
        shutil.copy2(npps4_src, default_dst)


def prepare_workspace(workdir: str, config_path: str | None = None, android_archives: str | None = None, db_root: str | None = None) -> str:
    """Create the mutable NPPS4 workspace and copy editable defaults.

    Returns a JSON string so Kotlin does not need to depend on Python objects.
    """
    root = Path(workdir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "data").mkdir(exist_ok=True)
    (root / "data" / "db").mkdir(parents=True, exist_ok=True)
    (root / "exports").mkdir(exist_ok=True)
    # NPPS4's FastAPI app mounts /static and creates Jinja templates from ROOT_DIR.
    # On Android the mutable ROOT_DIR is the app workspace. Kotlin may already
    # create these directories, so we must merge-copy bundled files into them
    # rather than only copying when the directory is absent. Without this,
    # /resources/maintenance/maintenance.php crashes with TemplateNotFound
    # after login succeeds.
    (root / "static").mkdir(exist_ok=True)
    (root / "templates").mkdir(exist_ok=True)
    _merge_copy_tree(BUNDLE_ROOT / "static", root / "static", overwrite=False)
    _merge_copy_tree(BUNDLE_ROOT / "templates", root / "templates", overwrite=False)
    # Android does not run Alembic. The mutable server DB is initialized in
    # android_main.py via SQLAlchemy metadata.create_all(), because Alembic
    # requires real migration-script paths while Chaquopy modules may live
    # inside APK/AssetFinder.
    archive_path = Path(android_archives).resolve() if android_archives else root / "cn" / "list_CN_Android"
    db_path = Path(db_root).resolve() if db_root else root / "data" / "db"
    # The public CDN archive directory is user-managed and should be treated as
    # read-only.  Do not create or modify it here: on Android 11+ that may crash
    # without MANAGE_EXTERNAL_STORAGE, and ordinary ZIP archives should remain
    # untouched.  Only create app-owned DB/cache directories under the workspace.
    try:
        if root in db_path.parents or db_path == root:
            db_path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # Chaquopy does not guarantee that arbitrary source-tree files are available
    # as real filesystem paths under AssetFinder. Extract the imported embedded
    # payload first, but never overwrite an existing user-owned workspace file.
    _extract_embedded_workspace_defaults(root, overwrite=False)

    # Install both RSA key families.  default_server_key.pem remains NPPS4/GL;
    # honoka_server_key.pem is used as CN/honoka fallback.
    _install_server_keys(root)
    src = BUNDLE_ROOT / "config.sample.toml"
    if src.exists():
        _copy_if_missing(src, root / "config.sample.toml")
    src = BUNDLE_ROOT / "cn_server_info_99_0_115.zip"
    _copy_cn_server_info_override(src, root / "cn_server_info_99_0_115.zip")

    for rel in ["external", "beatmaps"]:
        src = BUNDLE_ROOT / rel
        if src.exists():
            _copy_if_missing(src, root / rel)

    # Editable workspace files are user-owned after first creation.  Populate
    # missing defaults, but never repair, merge, or overwrite an existing hook.
    # Invalid user files are reported by normal validation/startup instead of
    # being silently reset behind the user's back.
    for filename in [
        "badwords.py",
        "login_bonus.py",
        "beatmap.py",
        "live_unit_drop.py",
        "live_box_drop.py",
    ]:
        _copy_if_missing(
            BUNDLE_ROOT / "external" / filename,
            root / "external" / filename,
        )

    # server_data.json is copied only on first creation.  A user may delete,
    # rename, or edit LOVEARROWSHOOT (or any other code); later starts must
    # preserve that exact file and must not inject bundled entries.
    _copy_if_missing(
        BUNDLE_ROOT / "npps4" / "server_data.json",
        root / "npps4" / "server_data.json",
    )
    schema = BUNDLE_ROOT / "npps4" / "server_data_schema.json"
    if schema.exists():
        _copy_if_missing(schema, root / "npps4" / "server_data_schema.json")

    cfg = Path(config_path).resolve() if config_path else root / "config.toml"
    # config.toml is also user-owned after first creation.  Create the bundled
    # default only when the file is absent; never canonicalize, migrate, repair,
    # or rewrite an existing file during startup.
    if not cfg.exists():
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(
            default_config(str(root), str(archive_path), str(db_path)),
            encoding="utf-8",
        )

    return json.dumps({
        "ok": True,
        "workdir": str(root),
        "config": str(cfg),
        "android_archives": str(archive_path),
        "server_info": str(archive_path / "99_0_115.zip"),
        "db_root": str(db_path),
    }, ensure_ascii=False)



def default_config(root: str, android_archives: str | None = None, db_root: str | None = None) -> str:
    root_path = Path(root).resolve()
    root = root_path.as_posix()
    android_archives = Path(android_archives).resolve().as_posix() if android_archives else f"{root}/cn/list_CN_Android"
    db_root = Path(db_root).resolve().as_posix() if db_root else f"{root}/data/db_cn_honoka"
    gl_archive_root = (root_path / "data" / "gl_archive_root").as_posix()
    return f'''# Generated by NPPS4 Android Wrapper.
# Mutable workspace: {root}

[main]
data_directory = "data"
secret_key = "Change this secret if you expose the server"
server_private_key = "default_server_key.pem"
server_private_key_password = ""
server_data = "npps4/server_data.json"
session_expiry = 259200
save_notes_list = false

[database]
url = "sqlite+aiosqlite:///data/main.sqlite3"

[download]
backend = ""
default_profile = "cn"

[download.profiles.cn]
enabled = true
backend = "cn_archive"
museum_unlock_policy = "all"
send_patched_server_info = true

[download.profiles.cn.n4dlapi]
server = ""
shared_key = ""

[download.profiles.cn.cn_archive]
android_archives = "{android_archives}"
ios_archives = ""
android_extracted = ""
ios_extracted = ""
db_root = "{db_root}"
application_version = "9.7.1"
client_version = "97.4.6"
update_package_type = 99
server_info_override = "99_0_115.zip"
android_server_info_override = "cn_server_info_99_0_115.zip"
ios_server_info_override = ""
gl_overlay_enabled = true
gl_overlay_server = "https://ll.sif.moe/npps4_dlapi"
gl_overlay_shared_key = ""
gl_overlay_cache = ""
gl_overlay_timeout = 30
gl_overlay_try_language_fallback = true
gl_overlay_negative_ttl = 300
android_extra_update_packages = []
ios_extra_update_packages = []
archive_access_manifest = "data/cn_update_overlays/archive_access_manifest.json"
main_scenario_unlock_policy = "normal"
subscenario_unlock_policy = "normal"
live_unlock_policy = "normal"
album_catalog_unlock_policy = "normal"

[download.profiles.gl]
enabled = true
backend = "n4dlapi"
museum_unlock_policy = "all"
send_patched_server_info = true

[download.profiles.gl.internal]
archive_root = "{gl_archive_root}"

[download.profiles.gl.n4dlapi]
server = "https://ll.sif.moe/npps4_dlapi"
shared_key = ""

[download.profiles.gl.none]
client_version = "59.4"

[game]
badwords = "external/badwords.py"
login_bonus = "external/login_bonus.py"
beatmaps = "external/beatmap.py"
live_unit_drop = "external/live_unit_drop.py"
live_box_drop = "external/live_box_drop.py"

[advanced]
base_xorpad = "eit4Ahph4aiX4ohmephuobei6SooX9xo"
application_key = "b6e6c940a93af2357ea3e0ace0b98afc"
consumer_key = "lovelive_test"
verify_xmc = true

[compat]
region = "dual"
cn_main_headers = true
cn_autocreate_ghome_users = true
cn_wrappers = true
cn_optional_stubs = false
daily_rotation_timezone = "auto"
live_continue_loveca_cost = 1

[iex]
enable_export = true
enable_import = true
bypass_signature = false

[gameplay]
energy_multiplier = 1
love_multiplier = 1
secretbox_cost_multiplier = 1
'''


def _migrate_cn_client_version(config_path: Path) -> None:
    """Upgrade old v4.18/v4.19 CN configs from 97.4 to honoka's 97.4.6.

    v4.19 preserved valid config.toml files to avoid clobbering the UI-selected
    profile. That also preserved the old two-part CN client_version, causing the
    CN client to redownload 99_0_*.zip forever after each restart.
    """
    try:
        text = config_path.read_text(encoding="utf-8")
    except Exception:
        return
    if (
        'backend = "cn_archive"' not in text
        and "backend = 'cn_archive'" not in text
        and "[download.profiles.cn.cn_archive]" not in text
    ):
        return
    new_text = re.sub(r'(client_version\s*=\s*["\'])97\.4(["\'])', r'\g<1>97.4.6\2', text)
    if new_text != text:
        try:
            bak = config_path.with_suffix(config_path.suffix + ".pre-v420-version.bak")
            if not bak.exists():
                bak.write_text(text, encoding="utf-8")
        except Exception:
            pass
        config_path.write_text(new_text, encoding="utf-8")



def _migrate_cn_main_headers(config_path: Path) -> None:
    """Enable honoka-style CN response headers for existing cn_archive profiles.

    Old v4.x configs kept this false to minimize behavior changes.  The CN
    client's post-update flow is closer to honoka-chan than to upstream NPPS4,
    so existing Android workspaces should be migrated instead of silently keeping
    the old header mode.
    """
    try:
        text = config_path.read_text(encoding="utf-8")
    except Exception:
        return
    if (
        'backend = "cn_archive"' not in text
        and "backend = 'cn_archive'" not in text
        and "[download.profiles.cn.cn_archive]" not in text
    ):
        return
    if 'region = "global"' in text or "region = 'global'" in text:
        return
    new_text = re.sub(r'(cn_main_headers\s*=\s*)false', r'\g<1>true', text, flags=re.IGNORECASE)
    if new_text != text:
        try:
            bak = config_path.with_suffix(config_path.suffix + ".pre-v423-cn-headers.bak")
            if not bak.exists():
                bak.write_text(text, encoding="utf-8")
        except Exception:
            pass
        config_path.write_text(new_text, encoding="utf-8")

def _migrate_profile_museum_policies(config_path: Path) -> None:
    """Move the old CN-only nested policy to independent CN/GL profile keys."""
    try:
        text = config_path.read_text(encoding="utf-8")
    except Exception:
        return

    legacy_value = "all"
    legacy_found = False
    nested_pattern = re.compile(
        r"(?ms)^\[download\.profiles\.cn\.cn_archive\]\s*$(.*?)(?=^\[|\Z)"
    )
    nested = nested_pattern.search(text)
    if nested:
        match = re.search(
            r"(?m)^museum_(?:bridge_)?unlock_policy\s*=\s*[\"'](normal|all)[\"']",
            nested.group(1),
        )
        if match:
            legacy_value = match.group(1)
            legacy_found = True
        cleaned = re.sub(
            r"(?m)^museum_(?:bridge_)?unlock_policy\s*=.*\n?", "", nested.group(0)
        )
        text = text[:nested.start()] + cleaned + text[nested.end():]

    for profile, default in (("cn", legacy_value), ("gl", "all")):
        section_pattern = re.compile(
            rf"(?ms)^\[download\.profiles\.{profile}\]\s*$(.*?)(?=^\[|\Z)"
        )
        section = section_pattern.search(text)
        if not section:
            continue
        existing = re.search(r"(?m)^museum_unlock_policy\s*=\s*[\"'](?:normal|all)[\"']", section.group(1))
        if profile == "cn" and legacy_found and existing:
            replacement = f'museum_unlock_policy = "{legacy_value}"'
            start = section.start(1) + existing.start()
            end = section.start(1) + existing.end()
            text = text[:start] + replacement + text[end:]
        elif not existing:
            insertion = f'museum_unlock_policy = "{default}"\n'
            text = text[:section.end()] + insertion + text[section.end():]

    config_path.write_text(text, encoding="utf-8")


def _remove_legacy_museum_transplant_config(config_path: Path) -> None:
    """Remove abandoned CN/GL Museum transplant options from existing configs."""
    try:
        text = config_path.read_text(encoding="utf-8")
    except Exception:
        return
    keys = ("museum_server_db", "museum_bridge_manifest", "cn_museum_experimental_catalog")
    new_text = text
    # Keep an operator's previous all/normal choice, but rename it to make clear
    # that it now controls only the native CN catalogue.
    if "museum_unlock_policy" not in new_text:
        new_text = re.sub(
            r"(?m)^(\s*)museum_bridge_unlock_policy(\s*=)",
            r"\1museum_unlock_policy\2",
            new_text,
        )
    for key in keys:
        new_text = re.sub(rf"(?m)^\s*{re.escape(key)}\s*=.*\n?", "", new_text)
    new_text = re.sub(r'(?m)^(\s*android_extra_update_packages\s*=\s*)\[[^\]]*(?:99_0_116|99_0_117)[^\]]*\]\s*$', r'\1[]', new_text)
    if new_text != text:
        try:
            bak = config_path.with_suffix(config_path.suffix + ".pre-v455-museum-cleanup.bak")
            if not bak.exists():
                bak.write_text(text, encoding="utf-8")
        except Exception:
            pass
        config_path.write_text(new_text, encoding="utf-8")


def _find_db_file(db_root: Path, name: str) -> bool:
    return any((db_root / candidate).is_file() for candidate in (f"{name}.db_", f"{name}.db", name))

REQUIRED_MASTER_DBS = ["achievement", "effort", "exchange", "game_mater", "item", "live", "museum", "scenario", "subscenario", "unit"]


def _archive_sort_key(path: Path) -> tuple[int, int, int, str]:
    stem = path.stem
    parts = stem.split("_")
    nums: list[int] = []
    for part in parts[:3]:
        try:
            nums.append(int(part))
        except ValueError:
            nums.append(-1)
    while len(nums) < 3:
        nums.append(-1)
    return nums[0], nums[1], nums[2], path.name


def _candidate_db_name(filename: str) -> str | None:
    base = Path(filename).name
    lower = base.lower()
    for name in REQUIRED_MASTER_DBS:
        if lower in (f"{name}.db_", f"{name}.db", name):
            return name
    return None


def extract_master_dbs_from_archives(android_archives: str, out_dir: str) -> str:
    """Extract NPPS4-readable master DBs from flat CN archive ZIPs.

    The CN CDN directory is used as a source, but the mutable extracted DBs are
    written to the app workspace.  This avoids requiring users to manually
    prepare db_root while keeping the 10+ GB CDN archives in the public folder.
    """
    archive_root = Path(android_archives).resolve()
    target = Path(out_dir).resolve()
    if not archive_root.is_dir():
        raise RuntimeError(f"CN archives directory not found: {archive_root}")
    target.mkdir(parents=True, exist_ok=True)
    found: dict[str, str] = {}
    zips = sorted(archive_root.glob("*.zip"), key=_archive_sort_key)
    if not zips:
        raise RuntimeError(f"No ZIP files found in CN archives directory: {archive_root}")
    for zp in zips:
        try:
            with zipfile.ZipFile(zp, "r") as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    db_name = _candidate_db_name(info.filename)
                    if db_name is None:
                        continue
                    out_name = Path(info.filename).name
                    if not out_name.endswith(".db_") and not out_name.endswith(".db"):
                        out_name = f"{db_name}.db_"
                    out_path = target / out_name
                    tmp_path = target / (out_name + ".tmp")
                    with zf.open(info, "r") as src, tmp_path.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    tmp_path.replace(out_path)
                    found[db_name] = f"{zp.name}:{info.filename}"
        except zipfile.BadZipFile:
            continue
    missing = [name for name in REQUIRED_MASTER_DBS if name not in found and not _find_db_file(target, name)]
    if missing:
        raise RuntimeError(
            "Could not extract all NPPS4 master DBs from CN archives. "
            f"Missing: {', '.join(missing)}. "
            "This means the selected folder is not the complete CN archive folder, "
            "or the DB files are not stored as plain .db_ files inside those ZIPs."
        )
    return json.dumps({"ok": True, "db_root": str(target), "found": found}, ensure_ascii=False)


def generate_honoka_master_dbs(workdir: str, config_path: str | None = None, out_dir: str | None = None) -> str:
    """Generate NPPS4 split master DBs from the bundled honoka main.db.

    This is the normal Android-wrapper path. It does not scan or edit CDN ZIPs.
    Set NPPS4_ROOT_DIR/NPPS4_CONFIG before importing any npps4.* module so
    modules which read config at import time do not see the blank defaults.
    """
    root = Path(workdir).resolve()
    cfg = Path(config_path).resolve() if config_path else root / "config.toml"
    prepare_workspace(str(root), str(cfg))
    _bootstrap(str(root), str(cfg))
    target = Path(out_dir).resolve() if out_dir else root / "data" / "db_cn_honoka"
    target.mkdir(parents=True, exist_ok=True)
    from npps4.tools.cn_honoka_master import generate_split_db, bundled_honoka_main_db

    files = generate_split_db(bundled_honoka_main_db(), str(target), overwrite=True)
    _replace_config_db_root(cfg, target)
    return json.dumps({"ok": True, "db_root": str(target), "files": files}, ensure_ascii=False)


def _replace_config_db_root(config_path: Path, db_root: Path) -> None:
    if not config_path.exists():
        return
    text = config_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    out: list[str] = []
    in_cn = False
    changed = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_cn = stripped == "[download.cn_archive]"
        if in_cn and stripped.startswith("db_root") and "=" in stripped:
            out.append(f'db_root = "{db_root.resolve().as_posix()}"')
            changed = True
        else:
            out.append(line)
    if changed:
        config_path.write_text("\n".join(out) + "\n", encoding="utf-8")



def _sqlite_literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return "X'" + bytes(value).hex() + "'"
    return "'" + str(value).replace("'", "''") + "'"


def _default_value_for_sqlite_type(sql_type: str):
    t = (sql_type or "").upper()
    if "INT" in t:
        return 0
    if any(x in t for x in ("REAL", "FLOA", "DOUB", "NUM", "DEC")):
        return 0.0
    if "BLOB" in t:
        return b""
    return ""


def _add_master_column(conn, table_name: str, col_info) -> None:
    """Add one missing master-DB column using SQLite-safe syntax.

    CN/Honoka split master DBs may persist across wrapper upgrades.  Newer
    NPPS4 ORM classes select columns such as release_tag and
    _encryption_release_id, so an older split DB can make login fail with
    "no such column" even though the Python server is otherwise healthy.
    """
    _cid, name, sql_type, notnull, dflt_value, pk = col_info
    if pk:
        raise RuntimeError(f"Cannot add missing primary-key column {table_name}.{name}")
    type_sql = sql_type or "TEXT"
    pieces = [f'ALTER TABLE "{table_name}" ADD COLUMN "{name}" {type_sql}']
    if dflt_value is not None:
        pieces.append(f"DEFAULT {dflt_value}")
    elif notnull:
        pieces.append(f"DEFAULT {_sqlite_literal(_default_value_for_sqlite_type(type_sql))}")
    if notnull:
        pieces.append("NOT NULL")
    conn.execute(" ".join(pieces))


def _ensure_master_encryption_columns(conn) -> None:
    # SQLAlchemy's master DB ORM uses the MaybeEncrypted mixin on many tables.
    # Some embedded/Honoka schemas and persisted older split DBs don't carry
    # those physical columns. Extra nullable columns are harmless for tables
    # which don't use them, while missing columns break SELECTs immediately.
    tables = [
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        if not str(row[0]).startswith("_") and row[0] != "sqlite_sequence"
    ]
    for table_name in tables:
        have = {row[1] for row in conn.execute(f'PRAGMA table_info("{table_name}")')}
        if "release_tag" not in have:
            conn.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "release_tag" TEXT')
        if "_encryption_release_id" not in have:
            conn.execute(f'ALTER TABLE "{table_name}" ADD COLUMN "_encryption_release_id" INTEGER')


def _repair_master_db_schema(db_root: Path) -> None:
    """Reconcile persisted split master DB schemas with embedded NPPS4 schemas.

    This is separate from the mutable server DB migration path.  The split
    master DBs are read-only game data from Honoka/CN archives, but on Android
    they live in app storage and survive APK upgrades.  Earlier wrapper builds
    generated or accepted DBs without NPPS4's MaybeEncrypted columns, which
    causes SQLAlchemy to fail at runtime when selecting live_setting_m.release_tag.
    """
    import sqlite3

    try:
        from npps4.tools.cn_honoka_master import DB_SOURCES, _create_sql_by_table, _insert_defaults
    except Exception:
        return

    for db_name in DB_SOURCES.keys():
        db_file = next((db_root / c for c in (f"{db_name}.db_", f"{db_name}.db", db_name) if (db_root / c).is_file()), None)
        if db_file is None:
            continue
        schemas = _create_sql_by_table(db_name)
        if not schemas:
            continue
        with sqlite3.connect(db_file) as conn:
            conn.execute("PRAGMA foreign_keys=OFF")
            expected = sqlite3.connect(":memory:")
            try:
                for create_sql in schemas.values():
                    expected.execute(create_sql)
                for table_name, create_sql in schemas.items():
                    exists = conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table_name,),
                    ).fetchone()
                    if exists is None:
                        conn.execute(create_sql)
                        continue
                    have = {row[1] for row in conn.execute(f'PRAGMA table_info("{table_name}")')}
                    for col in expected.execute(f'PRAGMA table_info("{table_name}")'):
                        if col[1] not in have:
                            _add_master_column(conn, table_name, col)
                _ensure_master_encryption_columns(conn)
                try:
                    _insert_defaults(conn)
                except Exception:
                    pass
                conn.commit()
            finally:
                expected.close()

def _ensure_master_db_root(workdir: str, config_path: str | None, android_archives: str | None, db_root: str | None) -> Path:
    requested = Path(db_root).resolve() if db_root else Path(workdir).resolve() / "data" / "db_cn_honoka"
    if all(_find_db_file(requested, name) for name in REQUIRED_MASTER_DBS):
        _repair_master_db_schema(requested)
        return requested

    # Do not treat client CDN ZIPs as the default master DB source.  Generate a
    # small server-side split-DB set from the bundled honoka main.db instead.
    target = Path(workdir).resolve() / "data" / "db_cn_honoka"
    generate_honoka_master_dbs(workdir, config_path, str(target))
    _repair_master_db_schema(target)
    return target


def _preflight_paths(android_archives: str | None, db_root: str | None) -> None:
    archive_root = Path(android_archives).resolve() if android_archives else None
    db_path = Path(db_root).resolve() if db_root else None
    problems: list[str] = []
    if archive_root is not None:
        if not archive_root.is_dir():
            problems.append(f"CN archives directory does not exist or is not a directory: {archive_root}")
        else:
            # Archives may be empty during initial setup, so warn via last_error only
            # instead of aborting here. The client download endpoints will return
            # empty lists until ZIPs are added.
            pass
    if db_path is None or not db_path.is_dir():
        problems.append(f"NPPS4 master DB directory does not exist: {db_path}")
    else:
        required = REQUIRED_MASTER_DBS
        missing = [name for name in required if not _find_db_file(db_path, name)]
        if missing:
            problems.append(
                "Missing NPPS4-readable master DB files in " + str(db_path) + ": " + ", ".join(missing) +
                ". Put files such as game_mater.db_, unit.db_, live.db_, effort.db_ in the public db/ folder, or edit config.toml/db_root."
            )
        else:
            # Catch the common mistake of putting CDN ZIPs or empty placeholder files
            # in db_root. NPPS4 needs extracted SQLite master DB files, not archives.
            import sqlite3
            table_checks = {
                "game_mater": "game_setting_m",
                "unit": "unit_m",
                "live": "live_track_m",
            }
            for db_name, table_name in table_checks.items():
                db_file = next((db_path / c for c in (f"{db_name}.db_", f"{db_name}.db", db_name) if (db_path / c).is_file()), None)
                if db_file is None:
                    continue
                try:
                    with sqlite3.connect(f"file:{db_file}?mode=ro", uri=True) as conn:
                        cur = conn.execute("select name from sqlite_master where type='table' and name=?", (table_name,))
                        if cur.fetchone() is None:
                            problems.append(f"Master DB {db_file.name} exists but lacks required table {table_name}. db_root must contain extracted NPPS4-readable SQLite master DBs, not raw ZIP archives or empty files.")
                except Exception as exc:
                    problems.append(f"Cannot open master DB {db_file.name} as SQLite: {exc}. db_root must contain extracted .db_ master DB files.")
    if problems:
        raise RuntimeError("Android wrapper preflight failed:\n" + "\n".join(f"- {p}" for p in problems))


def _set_state(**kwargs: Any) -> None:
    with _state_lock:
        _state.update(kwargs)
        th = _server_thread
        _state["thread_alive"] = bool(th and th.is_alive())


def _drop_module(name: str) -> None:
    """Remove a module and its parent-package attribute if present."""
    sys.modules.pop(name, None)
    parent_name, _, attr = name.rpartition(".")
    if parent_name and attr:
        parent = sys.modules.get(parent_name)
        if parent is not None and hasattr(parent, attr):
            try:
                delattr(parent, attr)
            except Exception:
                pass


def _reset_runtime_modules() -> None:
    """Clear modules whose import-time config may have been poisoned.

    A common Android UI path is pressing Stop/Status before Start. Older wrapper
    code imported android_main in that path, which imported npps4.config.config
    before NPPS4_ROOT_DIR/NPPS4_CONFIG were set. That cached a default config
    with download.backend == "", and every later start failed with
    "Missing or unknown backend ''."

    Before each real server start / DB import-export operation, remove the
    import-time-configured NPPS4 modules so they reload after _bootstrap has set
    the Android workspace and config.toml path. Do not drop npps4.tools, because
    the master-DB converter can be safely reused and has no active server state.
    """
    prefixes = (
        # Core config/import-time state.
        "npps4.config",
        # FastAPI app/router objects and handler registry are populated at import
        # time.  They MUST be rebuilt on every Android restart; otherwise a
        # second start after changing host/port hits errors such as
        # ``Endpoint achievement/unaccomplishList is already registered!`` from
        # npps4.idol.core.API_ROUTER_MAP.
        "npps4.app",
        "npps4.idol",
        "npps4.run",
        "npps4.game",
        "npps4.webview",
        "npps4.ghome",
        "npps4.sif2export",
        # DB/download/system modules also cache config-derived paths or import
        # game endpoints indirectly.
        "npps4.download",
        "npps4.db",
        "npps4.system",
        "npps4.errhand",
        "npps4.other",
    )
    names = [n for n in list(sys.modules) if n == "android_main" or any(n == p or n.startswith(p + ".") for p in prefixes)]
    # Drop children before parents.
    for name in sorted(names, key=lambda x: x.count("."), reverse=True):
        _drop_module(name)


def _bootstrap(workdir: str, config_path: str | None, reset_runtime: bool = True) -> None:
    root = Path(workdir).resolve()
    cfg = Path(config_path).resolve() if config_path else root / "config.toml"
    os.environ["NPPS4_ROOT_DIR"] = str(root)
    os.environ["NPPS4_CONFIG"] = str(cfg)
    os.chdir(root)
    if reset_runtime:
        _reset_runtime_modules()


def _serve(workdir: str, config_path: str | None, host: str, port: int, android_archives: str | None = None, db_root: str | None = None) -> None:
    try:
        _set_state(phase="preparing", running=False, host=host, port=port, last_error="")
        prepare_workspace(workdir, config_path, android_archives, db_root)
        actual_db_root = _ensure_master_db_root(workdir, config_path, android_archives, db_root)
        _preflight_paths(android_archives, str(actual_db_root))
        _bootstrap(workdir, config_path)
        import android_main  # imports NPPS4 after env has been set

        _set_state(phase="initializing_db", running=False)
        android_main.setup_server()
        _set_state(phase="running", running=True, started_at=time.time())
        android_main.start_server(host=host, port=port)
        _set_state(phase="stopped", running=False)
    except Exception:
        _set_state(phase="error", running=False, last_error=traceback.format_exc())
    finally:
        with _state_lock:
            _state["thread_alive"] = False


def start(workdir: str, config_path: str | None = None, host: str = "127.0.0.1", port: int = 51376, android_archives: str | None = None, db_root: str | None = None) -> str:
    global _server_thread
    with _state_lock:
        if _server_thread is not None and _server_thread.is_alive():
            return json.dumps({"ok": False, "error": "server already starting/running"}, ensure_ascii=False)
        _server_thread = threading.Thread(target=_serve, args=(workdir, config_path, host, int(port), android_archives, db_root), daemon=True)
        _server_thread.start()
    return json.dumps({"ok": True}, ensure_ascii=False)


def stop() -> str:
    try:
        # Do not import android_main just to stop a server which was never
        # started. Importing it before _bootstrap used to poison npps4.config
        # with blank defaults.
        android_main = sys.modules.get("android_main")
        if android_main is None:
            _set_state(phase="stopped", running=False)
            return json.dumps({"ok": True, "warning": "server was not started"}, ensure_ascii=False)
        try:
            android_main.stop_server()
            _set_state(phase="stopping")
            return json.dumps({"ok": True}, ensure_ascii=False)
        except RuntimeError as exc:
            if "not started" in str(exc):
                _set_state(phase="stopped", running=False)
                return json.dumps({"ok": True, "warning": str(exc)}, ensure_ascii=False)
            raise
    except Exception as exc:
        _set_state(last_error=traceback.format_exc())
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


def socket_health(host: str = "127.0.0.1", port: int = 51376, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def status() -> str:
    with _state_lock:
        s = dict(_state)
        th = _server_thread
        s["thread_alive"] = bool(th and th.is_alive())
    s["tcp_health"] = socket_health(s.get("host", "127.0.0.1"), int(s.get("port", 51376)), timeout=0.2)
    return json.dumps(s, ensure_ascii=False)


def reload_editable_data(workdir: str, config_path: str | None = None) -> str:
    """Hot-reload files edited by the Android wrapper without stopping Uvicorn.

    Safe for server_data.json and external/*.py hooks. config.toml scalar values
    are re-read where NPPS4 looks them up dynamically, but socket/database/backend
    changes still require a restart.
    """
    try:
        _bootstrap(workdir, config_path, reset_runtime=False)
        import importlib
        from npps4.config import config as cfg
        info: dict[str, object] = {}
        if hasattr(cfg, "reload_runtime_editable_data"):
            info.update(cfg.reload_runtime_editable_data())

        # server_data.json already reloads lazily on mtime change; force one parse
        # here so syntax/schema errors are reported immediately in the wrapper UI.
        try:
            from npps4 import data as server_data
            if hasattr(cfg, "get_server_data_path"):
                server_data.SERVER_DATA_PATH = cfg.get_server_data_path()
            server_data.server_data = None
            server_data.last_server_data_timestamp = 0
            server_data.get()
            info["server_data_reloaded"] = True
        except Exception as exc:
            raise RuntimeError(f"server_data.json reload failed: {exc}") from exc

        _set_state(last_error="")
        return json.dumps({"ok": True, "info": info}, ensure_ascii=False)
    except Exception:
        err = traceback.format_exc()
        _set_state(last_error=err)
        return json.dumps({"ok": False, "error": err}, ensure_ascii=False)


def export_database(workdir: str, config_path: str | None = None) -> bytes | None:
    _bootstrap(workdir, config_path)
    import android_main
    return android_main.export_database()


def import_database(workdir: str, data: bytes, config_path: str | None = None) -> int:
    _bootstrap(workdir, config_path)
    import android_main
    return int(android_main.import_database(data))


def zip_workspace(workdir: str, out_zip: str) -> str:
    root = Path(workdir).resolve()
    out = Path(out_zip).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    skip_prefixes = {root / "exports"}
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in root.rglob("*"):
            if any(p == sp or sp in p.parents for sp in skip_prefixes):
                continue
            if p.is_file():
                zf.write(p, p.relative_to(root).as_posix())
    return str(out)
