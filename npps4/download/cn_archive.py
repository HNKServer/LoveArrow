"""CN flat-archive download backend.

This backend serves the directory layout used by the CN client/honoka-chan
mirrors directly, without converting it to NPPS4-DLAPI's archive-root layout.

Expected archive names are like:
    list_CN_Android/1_578_1.zip
    list_CN_Android/2_3006_5.zip
    list_CN_Android/99_0_115.zip

Special CN server-info override:
    The CN data packages contain an encrypted root-level server_info.json with
    the original Shanda/SDO endpoint.  honoka-chan handles this by appending an
    extra 99_0_115.zip update package that overwrites the client-side server_info.
    This backend supports the same behavior.  All normal archives are served
    unchanged, while 99_0_115.zip is materialized dynamically from a real CN
    99_0_* template and patched to the current request host.

The server needs readable game master data. If [download.cn_archive].db_root
does not contain split DB files, this backend can generate a conservative CN
split-DB set from the bundled honoka-chan assets/main.db and use that as a
server-side read-only master-data provider. CDN ZIPs remain read-only files for
client download; they are not edited or treated as the default DB source.
"""

import asyncio
import glob
import importlib.resources as resources
import hashlib
import json
import os
import re
import shutil
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path

import fastapi
import fastapi.responses

from . import dltype
from . import gl_overlay
from .. import idoltype
from .. import util
from ..app import app
from ..tools import honky_cn
from ..config import config

_PACKAGE_RE = re.compile(r"^(?P<type>\d+)_(?P<id>\d+)_(?P<order>\d+)\.zip$")
_PLATFORM_MAP = {
    idoltype.PlatformType.iOS: "iOS",
    idoltype.PlatformType.Android: "Android",
}


@dataclass(frozen=True)
class _Package:
    platform: idoltype.PlatformType
    package_type: int
    package_id: int
    order: int
    # Filename exposed to the client.  For the server-info override this may be
    # 99_0_115.zip even if the local file has a human-readable name such as
    # 99_0_115（Termux专用）.zip.
    filename: str
    local_path: str
    size: int
    is_override: bool = False


@dataclass(frozen=True)
class _RawArchiveMember:
    zip_path: str
    member_name: str
    size: int
    crc: int


# v4.43's broad GL raw-file fallback is useful for archived content, but CN
# client UI binaries are version-coupled. Feeding later GL secretbox/WebView
# textures to CN 9.7.1 caused native SIGTRAP crashes. These namespaces must be
# satisfied by the exact CN archive (or an explicitly extracted CN directory),
# never by the GL cache/overlay.
_CN_NATIVE_ONLY_PREFIXES = (
    "assets/image/secretbox/",
    "en/assets/image/secretbox/",
    "assets/ui/secretbox/",
    "en/assets/ui/secretbox/",
    "assets/image/webview/",
    "en/assets/image/webview/",
)
_RAW_LOOKUP_CACHE: dict[tuple[idoltype.PlatformType, str], _RawArchiveMember | None] = {}
_RAW_LOOKUP_LOCK = threading.RLock()
_RAW_STATS = {"archive_hits": 0, "archive_misses": 0, "materialized": 0, "blocked_gl_fallbacks": 0}


def _normalize_raw_path(path: str) -> str:
    normalized = os.path.normpath(str(path or "").replace("\\", "/")).replace("\\", "/").lstrip("/")
    if not normalized or normalized == "." or normalized.startswith("../") or "/../" in f"/{normalized}/":
        raise ValueError(f"unsafe raw asset path: {path!r}")
    return normalized


def _cn_native_only(path: str) -> bool:
    try:
        normalized = _normalize_raw_path(path).lower()
    except ValueError:
        return True
    return normalized.startswith(_CN_NATIVE_ONLY_PREFIXES)


def _raw_package_priority(package: _Package) -> tuple[int, int, int, int, str]:
    # A 99 update ZIP overrides ordinary packages; within a family, later IDs
    # and orders win. This mirrors client update precedence without rewriting
    # any operator-owned archive.
    return (
        1 if package.package_type == int(_config.update_package_type) else 0,
        package.package_type,
        package.package_id,
        package.order,
        package.filename,
    )


def _lookup_cn_raw_many_sync(
    platform: idoltype.PlatformType,
    paths: list[str],
) -> dict[str, _RawArchiveMember | None]:
    normalized_paths: list[str] = []
    for path in paths:
        try:
            normalized_paths.append(_normalize_raw_path(path))
        except ValueError:
            continue

    result: dict[str, _RawArchiveMember | None] = {}
    unresolved: set[str] = set()
    with _RAW_LOOKUP_LOCK:
        for path in normalized_paths:
            key = (platform, path)
            if key in _RAW_LOOKUP_CACHE:
                result[path] = _RAW_LOOKUP_CACHE[key]
            else:
                unresolved.add(path)

    if unresolved:
        packages = sorted(_PACKAGES.get(platform, []), key=_raw_package_priority, reverse=True)
        for package in packages:
            if not unresolved or not os.path.isfile(package.local_path):
                break
            try:
                with zipfile.ZipFile(package.local_path, "r") as zf:
                    # Exact entry names are authoritative and inexpensive.
                    for target in tuple(unresolved):
                        try:
                            info = zf.getinfo(target)
                        except KeyError:
                            try:
                                info = zf.getinfo("./" + target)
                            except KeyError:
                                continue
                        member = _RawArchiveMember(package.local_path, info.filename, info.file_size, info.CRC)
                        result[target] = member
                        unresolved.remove(target)

                    # Some mirrors wrap every entry in one top-level directory.
                    # Accept a suffix only when it is unique inside this ZIP.
                    if unresolved:
                        suffix_candidates: dict[str, list[zipfile.ZipInfo]] = {target: [] for target in unresolved}
                        for info in zf.infolist():
                            if info.is_dir():
                                continue
                            name = info.filename.replace("\\", "/").lstrip("./")
                            for target in tuple(unresolved):
                                if name.endswith("/" + target):
                                    suffix_candidates[target].append(info)
                        for target, matches in suffix_candidates.items():
                            if len(matches) == 1:
                                info = matches[0]
                                result[target] = _RawArchiveMember(package.local_path, info.filename, info.file_size, info.CRC)
                                unresolved.discard(target)
            except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
                util.log(
                    "CN raw archive",
                    f"Skipping unreadable ZIP {package.local_path}: {type(exc).__name__}: {exc}",
                    severity=util.logging.WARNING,
                )

        with _RAW_LOOKUP_LOCK:
            for path in normalized_paths:
                key = (platform, path)
                member = result.get(path)
                _RAW_LOOKUP_CACHE[key] = member
                if member is None:
                    _RAW_STATS["archive_misses"] += 1
                else:
                    _RAW_STATS["archive_hits"] += 1

    for path in normalized_paths:
        result.setdefault(path, None)
    return result


def _raw_cache_path(platform: idoltype.PlatformType, path: str) -> str:
    normalized = _normalize_raw_path(path)
    platform_name = _PLATFORM_MAP.get(platform, str(platform))
    root = os.path.abspath(os.path.join(config.get_data_directory(), "cn_raw_cache", platform_name)).replace("\\", "/")
    local = os.path.abspath(os.path.join(root, normalized)).replace("\\", "/")
    if not local.startswith(root + "/"):
        raise ValueError(f"unsafe raw cache path: {path!r}")
    return local


def _materialize_cn_raw_sync(platform: idoltype.PlatformType, path: str) -> str | None:
    normalized = _normalize_raw_path(path)
    local = _raw_cache_path(platform, normalized)
    if os.path.isfile(local):
        return local
    member = _lookup_cn_raw_many_sync(platform, [normalized]).get(normalized)
    if member is None:
        return None
    os.makedirs(os.path.dirname(local), exist_ok=True)
    tmp = local + ".tmp"
    try:
        with zipfile.ZipFile(member.zip_path, "r") as zf, zf.open(member.member_name, "r") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
        if os.path.getsize(tmp) != member.size:
            raise OSError(f"raw asset size mismatch for {normalized}: expected {member.size}, got {os.path.getsize(tmp)}")
        os.replace(tmp, local)
        with _RAW_LOOKUP_LOCK:
            _RAW_STATS["materialized"] += 1
        util.log(
            "CN raw archive",
            f"Materialized {normalized} from {os.path.basename(member.zip_path)}::{member.member_name}",
            severity=util.logging.INFO,
        )
        return local
    except Exception:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass
        raise


async def _lookup_cn_raw_many(platform: idoltype.PlatformType, paths: list[str]):
    return await asyncio.to_thread(_lookup_cn_raw_many_sync, platform, paths)


async def _materialize_cn_raw(platform: idoltype.PlatformType, path: str):
    return await asyncio.to_thread(_materialize_cn_raw_sync, platform, path)


_config = config.CONFIG_DATA.download.cn_archive


def _abs_optional(path: str) -> str:
    if not path:
        return ""
    if os.path.isabs(path):
        return os.path.abspath(path).replace("\\", "/")
    return os.path.abspath(os.path.join(config.ROOT_DIR, path)).replace("\\", "/")


_ARCHIVE_DIRS = {
    idoltype.PlatformType.Android: _abs_optional(_config.android_archives),
    idoltype.PlatformType.iOS: _abs_optional(_config.ios_archives),
}
_EXTRACTED_DIRS = {
    idoltype.PlatformType.Android: _abs_optional(_config.android_extracted),
    idoltype.PlatformType.iOS: _abs_optional(_config.ios_extracted),
}
_SERVER_INFO_OVERRIDE_PATHS = {
    idoltype.PlatformType.Android: _abs_optional(_config.android_server_info_override),
    idoltype.PlatformType.iOS: _abs_optional(_config.ios_server_info_override),
}
_EXTRA_UPDATE_PATHS = {
    idoltype.PlatformType.Android: [_abs_optional(path) for path in _config.android_extra_update_packages],
    idoltype.PlatformType.iOS: [_abs_optional(path) for path in _config.ios_extra_update_packages],
}
_ARCHIVE_ACCESS_MANIFEST = _abs_optional(_config.archive_access_manifest)
_DB_ROOT = _abs_optional(_config.db_root) or os.path.join(config.get_data_directory(), "db").replace("\\", "/")
_PACKAGES: dict[idoltype.PlatformType, list[_Package]] = {}
_SERVER_INFO_OVERRIDES: dict[idoltype.PlatformType, _Package] = {}
_SERVER_INFO_MATERIALIZED: dict[tuple[idoltype.PlatformType, str], _Package] = {}
_PATCHED_UPDATE_MATERIALIZED: dict[tuple[idoltype.PlatformType, str, str, int, int], _Package] = {}
_BUNDLED_BANNER_PATHS: dict[str, str] = {}
_INITIALIZED = False


def _parse_package_name(filename: str) -> tuple[int, int, int] | None:
    m = _PACKAGE_RE.match(filename)
    if not m:
        return None
    return int(m.group("type")), int(m.group("id")), int(m.group("order"))


def _package_from_path(platform: idoltype.PlatformType, file: str) -> _Package | None:
    name = os.path.basename(file)
    parsed = _parse_package_name(name)
    if parsed is None or not os.path.isfile(file):
        return None
    pkg_type, pkg_id, order = parsed
    return _Package(
        platform=platform,
        package_type=pkg_type,
        package_id=pkg_id,
        order=order,
        filename=name,
        local_path=os.path.abspath(file).replace("\\", "/"),
        size=os.path.getsize(file),
    )


def _merge_extra_packages(platform: idoltype.PlatformType, base: list[_Package]) -> list[_Package]:
    # One package per (type, id, order).  An explicitly configured overlay wins
    # over a same-numbered file in the immutable archive directory.
    merged = {(p.package_type, p.package_id, p.order): p for p in base}
    for path in _EXTRA_UPDATE_PATHS.get(platform, []):
        package = _package_from_path(platform, path)
        if package is not None:
            merged[(package.package_type, package.package_id, package.order)] = package
    result = list(merged.values())
    result.sort(key=lambda p: (p.package_type, p.package_id, p.order, p.filename))
    return result


def _scan_platform(platform: idoltype.PlatformType) -> list[_Package]:
    root = _ARCHIVE_DIRS.get(platform) or ""
    if not root:
        return []
    result: list[_Package] = []
    for file in glob.glob(os.path.join(root, "*.zip")):
        name = os.path.basename(file)
        parsed = _parse_package_name(name)
        if parsed is None:
            continue
        pkg_type, pkg_id, order = parsed
        result.append(
            _Package(
                platform=platform,
                package_type=pkg_type,
                package_id=pkg_id,
                order=order,
                filename=name,
                local_path=os.path.abspath(file).replace("\\", "/"),
                size=os.path.getsize(file),
            )
        )
    result.sort(key=lambda p: (p.package_type, p.package_id, p.order))
    return _merge_extra_packages(platform, result)


def _zip_entry_bytes(path: str, names: tuple[str, ...]) -> bytes | None:
    try:
        with zipfile.ZipFile(path) as zf:
            entries = {name.replace("\\", "/"): name for name in zf.namelist()}
            for name in names:
                actual = entries.get(name)
                if actual is not None:
                    return zf.read(actual)
    except zipfile.BadZipFile as exc:
        raise RuntimeError(f"CN server_info override is not a valid ZIP file: {path}") from exc
    return None


def _read_override_server_info(local_path: str) -> bytes:
    # CN SIF1 update archives use a root-level server_info.json.  Older wrapper
    # builds accidentally bundled config/server_info.json because NPPS4/JP uses
    # that path; keep reading both for migration, but v4.24 always writes the
    # root-level file back into the honoka-style 99_0_115.zip.
    data = _zip_entry_bytes(local_path, ("server_info.json", "config/server_info.json"))
    if data is None:
        raise RuntimeError(
            "CN server_info override ZIP must contain server_info.json or config/server_info.json: "
            f"{local_path}"
        )
    return data


def _template_server_info_entry(template_path: str) -> zipfile.ZipInfo | None:
    try:
        with zipfile.ZipFile(template_path) as zf:
            entries = {info.filename.replace("\\", "/"): info for info in zf.infolist()}
            return entries.get("config/server_info.json") or entries.get("server_info.json")
    except zipfile.BadZipFile:
        return None


def _select_server_info_template(platform: idoltype.PlatformType, exposed_name: str) -> _Package | None:
    """Pick a real CN 99 update ZIP to use as the 99_0_115 shape template.

    honoka-chan's deployment notes build 99_0_115.zip by copying a real 99_0_113.zip,
    removing client_info.json, replacing root server_info.json, and serving that as
    the override package.  A tiny one-file ZIP is not equivalent: the CN native code
    appears to treat the package as an update-bundle stage and can abort later with a
    "download list is empty" assertion if the bundle shape is not what it expects.
    """
    candidates = [
        p
        for p in _PACKAGES.get(platform, [])
        if p.package_type == 99 and p.package_id == 0 and p.filename != exposed_name and os.path.isfile(p.local_path)
    ]
    if not candidates:
        return None

    # honoka docs explicitly use 99_0_113.zip as the source.  If a mirror lacks
    # that exact file, use a nearby/highest real 99_0_* package rather than the
    # synthetic override itself.
    preferred_orders = (113, 114, 112, 111, 110)
    for order in preferred_orders:
        matches = [p for p in candidates if p.order == order]
        if matches:
            return sorted(matches, key=lambda p: p.filename)[0]

    candidates.sort(key=lambda p: (p.order, p.filename), reverse=True)
    return candidates[0]


def _clone_zipinfo(src: zipfile.ZipInfo, filename: str | None = None) -> zipfile.ZipInfo:
    dst = zipfile.ZipInfo(filename or src.filename, src.date_time)
    dst.compress_type = src.compress_type
    dst.comment = src.comment
    dst.extra = src.extra
    dst.create_system = src.create_system
    dst.create_version = src.create_version
    dst.extract_version = src.extract_version
    dst.flag_bits = src.flag_bits
    dst.internal_attr = src.internal_attr
    dst.external_attr = src.external_attr
    dst.volume = src.volume
    return dst


def _server_info_base_url(request: fastapi.Request) -> str:
    root_path = str(request.scope.get("root_path") or "")
    return f"{request.url.scheme}://{request.url.netloc}{root_path}".rstrip("/")


def _decrypt_cn_server_info_candidates(data: bytes) -> tuple[bytes, honky_cn.CnHonkyMeta, str] | None:
    for name in ("server_info.json", "config/server_info.json"):
        try:
            plain, meta = honky_cn.decrypt_server_info(data, name)
            # Keep the check intentionally simple.  We only need to distinguish
            # an actual decrypted JSON server_info from random bytes.
            obj = json.loads(plain.decode("utf-8"))
            if isinstance(obj, dict) and obj.get("name") == "server_information":
                return plain, meta, name
        except Exception:
            continue
    return None


def _patch_cn_server_info_json(plain: bytes, base_url: str) -> bytes:
    obj = json.loads(plain.decode("utf-8"))
    base_url = base_url.rstrip("/")
    obj["domain"] = base_url
    obj["maintenance_uri"] = f"{base_url}/resources/maintenace/maintenance.php"
    obj["update_uri"] = f"{base_url}/resources/maintenace/update.php"
    obj["login_news_uri"] = f"{base_url}/webview.php/announce/index?0="
    obj["locked_user_uri"] = f"{base_url}/webview.php/static/index?id=13"
    obj["end_point"] = "/main.php"
    obj["consumer_key"] = config.CONFIG_DATA.advanced.consumer_key
    obj["application_key"] = config.CONFIG_DATA.advanced.application_key
    obj["server_version"] = get_server_version_string()

    api_uri = obj.get("api_uri")
    if isinstance(api_uri, dict):
        patched = {}
        for key, value in api_uri.items():
            if isinstance(key, str) and key.startswith("/"):
                patched[key] = f"{base_url}/main.php{key}"
            elif isinstance(value, str) and "/main.php/" in value:
                tail = value.split("/main.php", 1)[1]
                patched[key] = f"{base_url}/main.php{tail}"
            else:
                patched[key] = value
        obj["api_uri"] = patched

    # Preserve compact JSON because the CN client accepts it and it avoids
    # needless changes to the encrypted file size.  ensure_ascii=False preserves
    # any original localized strings from a real CN template.
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _pick_template_server_info(src: zipfile.ZipFile) -> tuple[zipfile.ZipInfo | None, bytes | None]:
    entries = {info.filename.replace("\\", "/"): info for info in src.infolist()}
    for name in ("server_info.json", "config/server_info.json"):
        info = entries.get(name)
        if info is not None:
            return info, src.read(info.filename)
    return None, None


def _generate_honoka_style_server_info_override(
    platform: idoltype.PlatformType,
    local_path: str,
    exposed_name: str,
    base_url: str,
) -> str:
    template = _select_server_info_template(platform, exposed_name)
    if template is None:
        util.log(
            "CN server_info override",
            "No real 99_0_* template ZIP found; serving the configured override ZIP as-is. "
            "This is less compatible with honoka-chan's CN update flow.",
            severity=util.logging.WARNING,
        )
        return local_path

    # Correct honoka behavior is not just moving a prepared ZIP around.  The
    # server_info from the *current* CN 99 template carries version/application
    # metadata for this client, but its host points at prod.game1.ll.sdo.com.
    # Decrypt that template, patch only the private-server endpoints and
    # security keys, then re-encrypt with the same CN HonokaMiku mode.  A stale
    # bundled server_info from an older package can otherwise make GHome use
    # localhost while the game layer still opens prod.game1.ll.sdo.com.
    template_info = None
    template_server_info = None
    template_meta = None
    template_entry_name = "server_info.json"
    try:
        with zipfile.ZipFile(template.local_path, "r") as src:
            template_info, encrypted = _pick_template_server_info(src)
            if encrypted is not None:
                dec = _decrypt_cn_server_info_candidates(encrypted)
                if dec is not None:
                    template_server_info, template_meta, template_entry_name = dec
    except zipfile.BadZipFile:
        template_info = None

    if template_server_info is None or template_meta is None:
        configured = _read_override_server_info(local_path)
        dec = _decrypt_cn_server_info_candidates(configured)
        if dec is None:
            raise RuntimeError(
                "CN server_info override is encrypted with an unsupported mode or is not a server_info JSON: "
                f"{local_path}"
            )
        template_server_info, template_meta, template_entry_name = dec
        util.log(
            "CN server_info override",
            "Could not decrypt server_info.json from the real 99 template; patched the configured fallback instead.",
            severity=util.logging.WARNING,
        )

    patched_plain = _patch_cn_server_info_json(template_server_info, base_url)
    encrypted_server_info = honky_cn.encrypt_server_info(patched_plain, template_meta, "server_info.json")
    hasher = hashlib.sha256()
    hasher.update(b"cn-dynamic-root-server-info-json-v4.27\0")
    for marker in (
        template.local_path,
        str(os.path.getsize(template.local_path)),
        local_path,
        str(os.path.getsize(local_path)),
        base_url,
        get_server_version_string(),
        config.CONFIG_DATA.advanced.consumer_key,
        config.CONFIG_DATA.advanced.application_key,
        template_entry_name,
    ):
        hasher.update(marker.encode("utf-8", errors="surrogateescape"))
        hasher.update(b"\0")
    hasher.update(patched_plain)
    digest = hasher.hexdigest()[:16]

    out_dir = os.path.join(config.get_data_directory(), "cn_server_info_override").replace("\\", "/")
    os.makedirs(out_dir, exist_ok=True)
    platform_name = _PLATFORM_MAP.get(platform, str(platform))
    out_path = os.path.join(out_dir, f"{platform_name}_{exposed_name}.{digest}.zip").replace("\\", "/")
    if os.path.isfile(out_path):
        return out_path

    with zipfile.ZipFile(template.local_path, "r") as src, zipfile.ZipFile(out_path, "w") as dst:
        if template_info is None:
            template_info, _ = _pick_template_server_info(src)
        for info in src.infolist():
            normalized = info.filename.replace("\\", "/")
            if normalized in {
                "client_info.json",
                "server_info.json",
                "config/server_info.json",
            }:
                continue
            if info.is_dir():
                dst.writestr(_clone_zipinfo(info), b"")
            else:
                dst.writestr(_clone_zipinfo(info), src.read(info.filename))

        if template_info is not None:
            out_info = _clone_zipinfo(template_info, "server_info.json")
        else:
            out_info = zipfile.ZipInfo("server_info.json")
            out_info.compress_type = zipfile.ZIP_DEFLATED
            out_info.external_attr = 0o644 << 16
        dst.writestr(out_info, encrypted_server_info)

    try:
        patched_obj = json.loads(patched_plain.decode("utf-8"))
        util.log(
            "CN server_info override",
            f"Generated honoka-style {exposed_name} from template {template.filename} -> {out_path}; "
            f"domain={patched_obj.get('domain')!r} server_version={patched_obj.get('server_version')!r}",
            severity=util.logging.INFO,
        )
    except Exception:
        util.log(
            "CN server_info override",
            f"Generated honoka-style {exposed_name} from template {template.filename} -> {out_path}",
            severity=util.logging.INFO,
        )
    return out_path


def _materialize_server_info_override(
    request: fastapi.Request,
    platform: idoltype.PlatformType,
    override: _Package,
) -> _Package:
    base_url = _server_info_base_url(request)
    cache_key = (platform, base_url)
    cached = _SERVER_INFO_MATERIALIZED.get(cache_key)
    if cached is not None and os.path.isfile(cached.local_path):
        return cached
    local_path = _generate_honoka_style_server_info_override(platform, override.local_path, override.filename, base_url)
    pkg = _Package(
        platform=platform,
        package_type=override.package_type,
        package_id=override.package_id,
        order=override.order,
        filename=override.filename,
        local_path=local_path,
        size=os.path.getsize(local_path),
        is_override=True,
    )
    _SERVER_INFO_MATERIALIZED[cache_key] = pkg
    return pkg


def _replace_cn_server_urls_in_plain_text(data: bytes, base_url: str) -> bytes:
    """Best-effort patch for plain JSON/text entries such as client_info.json.

    Most CN package URL state is in encrypted server_info.json, but some mirrors
    also carry plain helper metadata. This intentionally only runs inside the
    cn_archive backend and only for 99 update packages.
    """
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data
    host = base_url.split("://", 1)[1] if "://" in base_url else base_url
    replacements = {
        "http://prod.game1.ll.sdo.com": base_url,
        "https://prod.game1.ll.sdo.com": base_url,
        "prod.game1.ll.sdo.com": host,
        "http://prod.game2.ll.sdo.com": base_url,
        "https://prod.game2.ll.sdo.com": base_url,
        "prod.game2.ll.sdo.com": host,
    }
    patched = text
    for old, new in replacements.items():
        patched = patched.replace(old, new)
    if patched == text:
        return data
    return patched.encode("utf-8")


def _materialize_patched_update_package(
    request: fastapi.Request,
    platform: idoltype.PlatformType,
    package: _Package,
) -> _Package:
    """Patch server_info-bearing CN 99 update packages on the fly.

    v4.26 only generated a final 99_0_115 override. The logs show that the
    client can still end up using prod.game1.ll.sdo.com after the initial
    update. To match honoka-chan more defensively, every 99 update ZIP which
    contains server_info.json/config/server_info.json is now patched to the
    current request host. This prevents an earlier/later real update package
    from overwriting the local endpoint again.
    """
    if package.is_override:
        return _materialize_server_info_override(request, platform, package)

    update_type = int(_config.update_package_type)
    if package.package_type != update_type:
        return package

    base_url = _server_info_base_url(request)
    try:
        mtime = int(os.path.getmtime(package.local_path))
    except OSError:
        return package
    cache_key = (platform, base_url, package.local_path, package.size, mtime)
    cached = _PATCHED_UPDATE_MATERIALIZED.get(cache_key)
    if cached is not None and os.path.isfile(cached.local_path):
        return cached

    hasher = hashlib.sha256()
    hasher.update(b"cn-patch-all-99-server-info-v4.27\0")
    for marker in (
        package.local_path,
        str(package.size),
        str(mtime),
        package.filename,
        base_url,
        get_server_version_string(),
        config.CONFIG_DATA.advanced.consumer_key,
        config.CONFIG_DATA.advanced.application_key,
    ):
        hasher.update(marker.encode("utf-8", errors="surrogateescape"))
        hasher.update(b"\0")
    digest = hasher.hexdigest()[:16]
    out_dir = os.path.join(config.get_data_directory(), "cn_patched_update_packages").replace("\\", "/")
    os.makedirs(out_dir, exist_ok=True)
    platform_name = _PLATFORM_MAP.get(platform, str(platform))
    out_path = os.path.join(out_dir, f"{platform_name}_{package.filename}.{digest}.zip").replace("\\", "/")

    if os.path.isfile(out_path):
        patched = _Package(
            platform=platform,
            package_type=package.package_type,
            package_id=package.package_id,
            order=package.order,
            filename=package.filename,
            local_path=out_path,
            size=os.path.getsize(out_path),
            is_override=False,
        )
        _PATCHED_UPDATE_MATERIALIZED[cache_key] = patched
        return patched

    changed = False
    server_info_entries = 0
    client_info_patched = False
    tmp_path = out_path + ".tmp"
    try:
        with zipfile.ZipFile(package.local_path, "r") as src, zipfile.ZipFile(tmp_path, "w") as dst:
            for info in src.infolist():
                normalized = info.filename.replace("\\", "/")
                if info.is_dir():
                    dst.writestr(_clone_zipinfo(info), b"")
                    continue

                data = src.read(info.filename)
                if normalized in {"server_info.json", "config/server_info.json"}:
                    dec = _decrypt_cn_server_info_candidates(data)
                    if dec is not None:
                        plain, meta, _entry_name = dec
                        patched_plain = _patch_cn_server_info_json(plain, base_url)
                        encrypted = honky_cn.encrypt_server_info(patched_plain, meta, normalized)
                        dst.writestr(_clone_zipinfo(info), encrypted)
                        changed = True
                        server_info_entries += 1
                        continue

                if normalized == "client_info.json":
                    patched_data = _replace_cn_server_urls_in_plain_text(data, base_url)
                    if patched_data != data:
                        dst.writestr(_clone_zipinfo(info), patched_data)
                        changed = True
                        client_info_patched = True
                        continue

                dst.writestr(_clone_zipinfo(info), data)

        if not changed:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            _PATCHED_UPDATE_MATERIALIZED[cache_key] = package
            return package

        os.replace(tmp_path, out_path)
        patched = _Package(
            platform=platform,
            package_type=package.package_type,
            package_id=package.package_id,
            order=package.order,
            filename=package.filename,
            local_path=out_path,
            size=os.path.getsize(out_path),
            is_override=False,
        )
        _PATCHED_UPDATE_MATERIALIZED[cache_key] = patched
        util.log(
            "CN update package patch",
            f"Patched {package.filename} -> {out_path}; "
            f"server_info_entries={server_info_entries} client_info_patched={client_info_patched} "
            f"domain={base_url!r}",
            severity=util.logging.INFO,
        )
        return patched
    except Exception as exc:
        try:
            if os.path.isfile(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass
        util.log(
            "CN update package patch",
            f"Failed to patch {package.filename}; serving original file. error={type(exc).__name__}: {exc}",
            severity=util.logging.WARNING,
        )
        return package


def _build_server_info_override(platform: idoltype.PlatformType) -> _Package | None:
    local_path = _SERVER_INFO_OVERRIDE_PATHS.get(platform) or ""
    if not local_path:
        return None
    if not os.path.isfile(local_path):
        raise RuntimeError(f"CN server_info override file is invalid: {local_path}")

    exposed_name = _config.server_info_override or os.path.basename(local_path)
    parsed = _parse_package_name(exposed_name)
    if parsed is None:
        raise RuntimeError(
            "[download.cn_archive].server_info_override must look like '<type>_<id>_<order>.zip', "
            f"got: {exposed_name!r}"
        )
    pkg_type, pkg_id, order = parsed

    # Keep the public file name exactly 99_0_115.zip.  The actual
    # honoka-shaped/patched ZIP is materialized lazily per request so the
    # generated server_info can use the real request host (127.0.0.1, LAN IP,
    # or a reverse-proxy host) instead of a stale bundled value.

    return _Package(
        platform=platform,
        package_type=pkg_type,
        package_id=pkg_id,
        order=order,
        filename=exposed_name,
        local_path=local_path,
        size=os.path.getsize(local_path),
        is_override=True,
    )


def _effective_packages(platform: idoltype.PlatformType, request: fastapi.Request | None = None) -> list[_Package]:
    """Return packages after applying the 99_0_115 replacement rule."""
    packages = list(_PACKAGES.get(platform, []))
    override = _SERVER_INFO_OVERRIDES.get(platform)
    if override is not None:
        if request is not None:
            override = _materialize_server_info_override(request, platform, override)
        packages = [p for p in packages if p.filename != override.filename]
        packages.append(override)
    packages.sort(key=lambda p: (p.package_type, p.package_id, p.order, p.filename))
    return packages


def _url_for_archive(request: fastapi.Request, package: _Package) -> str:
    platform_name = _PLATFORM_MAP[package.platform]
    return str(request.url_for("cn_archives", path=f"{platform_name}/{package.filename}"))


def _url_for_extracted(request: fastapi.Request, platform: idoltype.PlatformType, path: str) -> str:
    platform_name = _PLATFORM_MAP[platform]
    sanitized = os.path.normpath(path.replace("\\", "/").replace("..", "")).replace("\\", "/")
    if sanitized.startswith("/"):
        sanitized = sanitized[1:]
    return str(request.url_for("cn_extracted", path=f"{platform_name}/{sanitized}"))


def _platform_from_path(path: str) -> tuple[idoltype.PlatformType, str]:
    normalized = path.replace("\\", "/")
    platform_name, _, rest = normalized.partition("/")
    for platform, name in _PLATFORM_MAP.items():
        if platform_name.lower() == name.lower():
            return platform, rest
    raise fastapi.HTTPException(404, detail="unknown platform")


def _safe_file_under(root: str, rest: str) -> str:
    local = os.path.abspath(os.path.join(root, os.path.normpath(rest.replace("..", "")))).replace("\\", "/")
    root_abs = os.path.abspath(root).replace("\\", "/")
    if not local.startswith(root_abs + "/") or not os.path.isfile(local):
        raise fastapi.HTTPException(404)
    return local


@app.core.get("/cn-archives/{path:path}", name="cn_archives")
async def cn_archives(request: fastapi.Request, path: str):
    platform, rest = _platform_from_path(path)

    # Replacement server_info package wins over any same-named package in the
    # raw archive directory.  This mirrors honoka-chan's 99_0_115 override idea
    # without mutating the operator's original data mirror.
    override = _SERVER_INFO_OVERRIDES.get(platform)
    if override is not None and rest == override.filename:
        override = _materialize_server_info_override(request, platform, override)
        return fastapi.responses.FileResponse(override.local_path, media_type="application/zip")

    for package in _effective_packages(platform, request):
        if package.filename != rest:
            continue
        if package.package_type == int(_config.update_package_type):
            package = _materialize_patched_update_package(request, platform, package)
        return fastapi.responses.FileResponse(package.local_path, media_type="application/zip")

    root = _ARCHIVE_DIRS.get(platform) or ""
    if not root:
        raise fastapi.HTTPException(404)
    return fastapi.responses.FileResponse(_safe_file_under(root, rest), media_type="application/zip")


def _existing_file_under(root: str, rest: str) -> str | None:
    if not root:
        return None
    try:
        return _safe_file_under(root, rest)
    except fastapi.HTTPException:
        return None


def _bundled_banner_alias(path: str) -> str | None:
    """Resolve CN KLB ``.imag`` cache keys to bundled PNG thumbnails."""
    direct = _BUNDLED_BANNER_PATHS.get(path)
    if direct and os.path.isfile(direct):
        return direct
    if path.endswith(".imag"):
        direct = _BUNDLED_BANNER_PATHS.get(path[:-5])
        if direct and os.path.isfile(direct):
            return direct
    return None


@app.core.get("/cn-extracted/{path:path}", name="cn_extracted")
async def cn_extracted(path: str):
    platform, rest = _platform_from_path(path)
    try:
        normalized_rest = _normalize_raw_path(rest)
    except ValueError:
        raise fastapi.HTTPException(404) from None
    bundled = _bundled_banner_alias(normalized_rest)
    if bundled is not None:
        util.log(
            "CN bundled banner",
            f"Serving {normalized_rest} from {bundled}",
            severity=util.logging.INFO,
        )
        return fastapi.responses.FileResponse(bundled, media_type="image/png")
    root = _EXTRACTED_DIRS.get(platform) or ""
    local = _existing_file_under(root, rest)
    if local is not None:
        return fastapi.responses.FileResponse(local)

    # Resolve the exact CN file out of the operator's ZIP archive before any
    # cross-version network fallback. This lets Android users keep their large
    # CDN as ZIPs instead of pre-extracting tens of gigabytes.
    try:
        local = await _materialize_cn_raw(platform, rest)
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        util.log(
            "CN raw archive",
            f"Could not materialize {rest}: {type(exc).__name__}: {exc}",
            severity=util.logging.WARNING,
        )
        local = None
    if local is not None:
        return fastapi.responses.FileResponse(local)

    if _cn_native_only(rest):
        with _RAW_LOOKUP_LOCK:
            _RAW_STATS["blocked_gl_fallbacks"] += 1
        util.log(
            "CN raw archive",
            f"Blocked incompatible GL fallback for CN-native UI asset: {rest}",
            severity=util.logging.WARNING,
        )
        raise fastapi.HTTPException(404)

    overlay = await gl_overlay.materialize(platform, rest)
    if overlay is not None:
        return fastapi.responses.FileResponse(overlay)
    raise fastapi.HTTPException(404)


@app.core.get("/npps4/android/gl-overlay.json")
async def cn_gl_overlay_status_endpoint():
    return fastapi.responses.JSONResponse(gl_overlay.status())


def get_server_version() -> tuple[int, int]:
    return util.parse_sif_version(_config.client_version)


def get_server_version_string() -> str:
    return str(_config.client_version).strip()


def _same_cn_version(a: str, b: str) -> bool:
    return str(a or "").strip() == str(b or "").strip()


_GENERATED_DB_ROOT: str | None = None


def _find_db_in_root(root: str, name: str) -> str | None:
    candidates = [
        os.path.join(root, f"{name}.db_"),
        os.path.join(root, f"{name}.db"),
        os.path.join(root, name),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate.replace("\\", "/")
    return None


def _ensure_generated_honoka_root() -> str:
    global _GENERATED_DB_ROOT
    if _GENERATED_DB_ROOT:
        return _GENERATED_DB_ROOT
    from ..tools.cn_honoka_master import ensure_builtin_split_db

    root = ensure_builtin_split_db()
    _GENERATED_DB_ROOT = root
    return root


def get_db_path(name: str) -> str:
    found = _find_db_in_root(_DB_ROOT, name)
    if found:
        return found

    # Fallback to a server-side CN master-data set generated from honoka-chan's
    # bundled assets/main.db. This is not scraped from a running client or from
    # the CDN ZIPs. It is prepared once under data/db_cn_honoka and then opened
    # read-only by NPPS4's normal DB layer.
    generated = _ensure_generated_honoka_root()
    found = _find_db_in_root(generated, name)
    if found:
        return found

    raise RuntimeError(
        f"Database '{name}' not found in CN db_root {_DB_ROOT} or generated honoka root {generated}"
    )


def _cn_update_package_infos(request: fastapi.Request, platform: idoltype.PlatformType, latest_str: str) -> list[dltype.UpdateInfo]:
    package_type = int(_config.update_package_type)
    packages = [p for p in _effective_packages(platform, request) if p.package_type == package_type]

    # honoka-chan appends 99_0_115.zip when it exists, because it carries the
    # server_info override for the CN client.  With android_server_info_override
    # / ios_server_info_override set, the replacement file is guaranteed to be
    # included even if the raw archive folder does not contain 99_0_115.zip.
    override_name = _config.server_info_override
    if override_name and all(p.filename != override_name for p in packages):
        for p in _effective_packages(platform, request):
            if p.filename == override_name:
                packages.append(p)
                break

    result: list[dltype.UpdateInfo] = []
    for p in sorted(packages, key=lambda p: (p.package_id, p.order)):
        p = _materialize_patched_update_package(request, platform, p)
        result.append(dltype.UpdateInfo(url=_url_for_archive(request, p), size=p.size, checksums=dltype.Checksum(), version=latest_str))
    return result


async def get_update_files_raw(
    request: fastapi.Request, platform: idoltype.PlatformType, install_version: str, external_version: str
) -> list[dltype.UpdateInfo]:
    latest_str = get_server_version_string()
    # CN 9.7.x persists the exact package-version string from update responses.
    # honoka-chan uses 97.4.6.  Returning/truncating this as 97.4 makes the
    # client download 99_0_*.zip again on every launch and prevents it from
    # reaching /download/batch and /download/additional.
    if _same_cn_version(external_version, latest_str):
        util.log(
            "CN download/update",
            f"up-to-date install_version={install_version!r} external_version={external_version!r} latest={latest_str!r}; returning 0 update packages",
            severity=util.logging.INFO,
        )
        return []
    result = _cn_update_package_infos(request, platform, latest_str)
    util.log(
        "CN download/update",
        f"install_version={install_version!r} external_version={external_version!r} latest={latest_str!r}; returning {len(result)} update packages",
        severity=util.logging.INFO,
    )
    return result


async def get_update_files(
    request: fastapi.Request, platform: idoltype.PlatformType, from_client_version: tuple[int, int]
) -> list[dltype.UpdateInfo]:
    latest = get_server_version()
    if from_client_version == latest:
        return []
    return _cn_update_package_infos(request, platform, get_server_version_string())


async def get_batch_files(
    request: fastapi.Request, platform: idoltype.PlatformType, package_type: int, exclude: list[int]
) -> list[dltype.BatchInfo]:
    requested_package_type = package_type
    # CN first-run quirk copied from honoka-chan: the client asks batch type 0
    # while size calculation expects [0, 4].  Type 0 is fetched by additional;
    # batch should return type 4 only.
    if package_type == 0:
        package_type = 4

    excluded = set(exclude)
    result: list[dltype.BatchInfo] = []
    for p in _effective_packages(platform, request):
        if p.package_type != package_type or p.package_id in excluded:
            continue
        result.append(dltype.BatchInfo(url=_url_for_archive(request, p), size=p.size, checksums=dltype.Checksum(), packageId=p.package_id))
    util.log(
        "CN download/batch",
        f"requested_type={requested_package_type} effective_type={package_type} excluded={len(excluded)}; returning {len(result)} packages",
        severity=util.logging.INFO,
    )
    return result


async def get_single_package(
    request: fastapi.Request, platform: idoltype.PlatformType, package_type: int, package_id: int
) -> list[dltype.BaseInfo] | None:
    result = [
        dltype.BaseInfo(url=_url_for_archive(request, p), size=p.size, checksums=dltype.Checksum())
        for p in _effective_packages(platform, request)
        if p.package_type == package_type and p.package_id == package_id
    ]
    if not result:
        return None
    return result


async def get_raw_files(request: fastapi.Request, platform: idoltype.PlatformType, files: list[str]) -> list[dltype.BaseInfo]:
    result: list[dltype.BaseInfo] = []
    base = _EXTRACTED_DIRS.get(platform) or ""
    normalized_by_original: dict[str, str] = {}
    unresolved: list[str] = []
    sizes: dict[str, int] = {}

    for file in files:
        try:
            sanitized = _normalize_raw_path(file)
        except ValueError:
            sanitized = ""
        normalized_by_original[file] = sanitized
        local = os.path.join(base, sanitized) if base and sanitized else ""
        bundled = _bundled_banner_alias(sanitized)
        if bundled is not None:
            sizes[file] = os.path.getsize(bundled)
            util.log(
                "CN bundled banner",
                f"Described {sanitized} size={sizes[file]}",
                severity=util.logging.INFO,
            )
            continue
        # Never reuse an already-cached GL binary for a version-coupled CN UI
        # namespace. Exact extracted/CN-ZIP content remains authoritative.
        cached = None if _cn_native_only(sanitized) else gl_overlay.cached_file(platform, sanitized)
        if local and os.path.isfile(local):
            sizes[file] = os.path.getsize(local)
        elif cached:
            sizes[file] = os.path.getsize(cached)
        elif sanitized:
            unresolved.append(sanitized)

    archive_members = await _lookup_cn_raw_many(platform, list(dict.fromkeys(unresolved))) if unresolved else {}
    overlay_missing: list[str] = []
    for original, sanitized in normalized_by_original.items():
        if original in sizes or not sanitized:
            continue
        member = archive_members.get(sanitized)
        if member is not None:
            sizes[original] = member.size
        elif not _cn_native_only(sanitized):
            overlay_missing.append(original)

    if overlay_missing and gl_overlay.enabled():
        described = await gl_overlay.describe_many(platform, overlay_missing)
        for file, info in described.items():
            if info is not None:
                sizes[file] = info.size

    for file in files:
        result.append(
            dltype.BaseInfo(
                url=_url_for_extracted(request, platform, file),
                size=sizes.get(file, 0),
                checksums=dltype.Checksum(),
            )
        )
    return result


def preflight() -> dict[str, object]:
    warnings: list[str] = []
    info: dict[str, object] = {
        "backend": "cn_archive",
        "archives": {},
        "extracted": {},
        "gl_overlay": gl_overlay.status(),
        "warnings": warnings,
    }
    for platform, name in _PLATFORM_MAP.items():
        archive_root = _ARCHIVE_DIRS.get(platform) or ""
        archive_count = len(_PACKAGES.get(platform, [])) if _INITIALIZED else (len(_scan_platform(platform)) if archive_root and os.path.isdir(archive_root) else 0)
        info["archives"][name] = {"root": archive_root, "exists": bool(archive_root and os.path.isdir(archive_root)), "zip_count": archive_count}
        if archive_root and not os.path.isdir(archive_root):
            warnings.append(f"{name} archive directory does not exist: {archive_root}")
        elif archive_root and archive_count <= 0:
            warnings.append(f"{name} archive directory contains no recognized <type>_<id>_<order>.zip files: {archive_root}")

        extracted_root = _EXTRACTED_DIRS.get(platform) or ""
        info["extracted"][name] = {"root": extracted_root, "exists": bool(extracted_root and os.path.isdir(extracted_root))}
        if not extracted_root and not gl_overlay.enabled():
            warnings.append(f"{name} extracted directory is not configured and GL overlay is disabled; missing raw files will return 404")
        elif not extracted_root and gl_overlay.enabled():
            warnings.append(f"{name} extracted directory is not configured; missing raw files will be fetched and cached through the GL overlay")
        elif not os.path.isdir(extracted_root):
            warnings.append(f"{name} extracted directory does not exist: {extracted_root}")

    if _config.server_info_override and not _SERVER_INFO_OVERRIDES:
        warnings.append("No prepared CN server_info override ZIP is configured; CN clients may keep the CDN/server-provided server_info. Do not rely on generic JP server_info injection for CN.")
    elif _SERVER_INFO_OVERRIDES:
        info["server_info_override"] = {
            _PLATFORM_MAP[p]: {"filename": pkg.filename, "local_path": pkg.local_path, "size": pkg.size}
            for p, pkg in _SERVER_INFO_OVERRIDES.items()
        }
    info["extra_update_packages"] = {
        _PLATFORM_MAP[platform]: [
            {"path": path, "exists": os.path.isfile(path), "filename": os.path.basename(path)}
            for path in _EXTRA_UPDATE_PATHS.get(platform, [])
        ]
        for platform in _PLATFORM_MAP
    }
    for platform, paths in _EXTRA_UPDATE_PATHS.items():
        for path in paths:
            if path and not os.path.isfile(path):
                warnings.append(f"{_PLATFORM_MAP[platform]} extra update package does not exist yet: {path}")
            elif path and _parse_package_name(os.path.basename(path)) is None:
                warnings.append(f"{_PLATFORM_MAP[platform]} extra update package has an unsupported filename: {path}")
    archive_manifest = None
    if _ARCHIVE_ACCESS_MANIFEST and os.path.isfile(_ARCHIVE_ACCESS_MANIFEST):
        try:
            with open(_ARCHIVE_ACCESS_MANIFEST, "r", encoding="utf-8") as fh:
                archive_manifest = json.load(fh)
        except Exception as exc:
            warnings.append(f"Archive-access manifest cannot be read: {type(exc).__name__}: {exc}")
    info["archive_access"] = {
        "manifest": _ARCHIVE_ACCESS_MANIFEST,
        "manifest_exists": bool(_ARCHIVE_ACCESS_MANIFEST and os.path.isfile(_ARCHIVE_ACCESS_MANIFEST)),
        "policies": {
            "main_scenario": str(_config.main_scenario_unlock_policy),
            "side_story": str(_config.subscenario_unlock_policy),
            "live": str(_config.live_unlock_policy),
            "album_catalog": str(_config.album_catalog_unlock_policy),
        },
    }
    info["home_banner_assets"] = {
        key: {"local_path": value, "exists": bool(value and os.path.isfile(value))}
        for key, value in _BUNDLED_BANNER_PATHS.items()
    }
    info["cn_raw_archive"] = {
        "cache_root": os.path.join(config.get_data_directory(), "cn_raw_cache").replace("\\", "/"),
        "lookup_entries": len(_RAW_LOOKUP_CACHE),
        "stats": dict(_RAW_STATS),
        "native_only_prefixes": list(_CN_NATIVE_ONLY_PREFIXES),
    }
    info["patched_update_package_cache"] = {
        "entries": len(_PATCHED_UPDATE_MATERIALIZED),
        "paths": [
            {"filename": pkg.filename, "local_path": pkg.local_path, "size": pkg.size}
            for pkg in _PATCHED_UPDATE_MATERIALIZED.values()
            if isinstance(pkg, _Package) and pkg.local_path
        ][:20],
    }
    return info


@app.core.get("/npps4/android/preflight.json")
async def cn_archive_preflight_endpoint():
    return fastapi.responses.JSONResponse(preflight())


def _bundled_asset_bytes(package: str, filename: str) -> bytes:
    try:
        return resources.files(package).joinpath(filename).read_bytes()
    except Exception:
        rel = package.removeprefix("npps4.assets.")
        fallback = os.path.join(os.path.dirname(__file__), "..", "assets", rel, filename)
        with open(os.path.abspath(fallback), "rb") as fh:
            return fh.read()


def _write_if_missing(path: str, data: bytes) -> bool:
    if not path or os.path.isfile(path):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
    return True


def _write_if_changed(path: str, data: bytes) -> bool:
    if not path:
        return False
    try:
        if os.path.isfile(path) and Path(path).read_bytes() == data:
            return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    Path(tmp).write_bytes(data)
    os.replace(tmp, path)
    return True


def _cleanup_obsolete_museum_transplant_artifacts() -> None:
    """Delete only NPPS4-generated files from the abandoned GL-to-CN Museum experiment."""
    data_root = Path(config.get_data_directory())
    generated_files = (
        data_root / "cn_update_overlays" / "museum.server.db",
        data_root / "cn_update_overlays" / "museum_bridge_manifest.json",
        data_root / "cn_update_overlays" / "99_0_116.zip",
        data_root / "cn_update_overlays" / "99_0_117.zip",
    )
    for path in generated_files:
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            util.log(
                "CN Museum cleanup",
                f"Could not remove obsolete generated file {path}: {type(exc).__name__}: {exc}",
                severity=util.logging.WARNING,
            )
    for path in (
        data_root / "cn_content_package_overlays",
        data_root / "cn_content_raw",
    ):
        try:
            if path.is_dir():
                shutil.rmtree(path)
        except OSError as exc:
            util.log(
                "CN Museum cleanup",
                f"Could not remove obsolete generated directory {path}: {type(exc).__name__}: {exc}",
                severity=util.logging.WARNING,
            )


def _ensure_bundled_support_assets() -> None:
    """Install server-owned CN banner support assets.

    The data-transfer thumbnail is a genuine CN WebView resource pair packed in
    a final type-4 full-data package.  The operator's archive mirror remains
    immutable; this package is generated under NPPS4's data directory and merged
    into the normal batch list after the stock 4_0_563 package.
    """
    try:
        banner_root = os.path.join(config.get_data_directory(), "cn_home_banner").replace("\\", "/")
        package_root = os.path.join(config.get_data_directory(), "cn_builtin_packages").replace("\\", "/")
        package_path = os.path.join(package_root, "4_0_999.zip").replace("\\", "/")
        _write_if_changed(package_path, _bundled_asset_bytes("npps4.assets.cn_home_banner", "4_0_999.zip"))
        extra = _EXTRA_UPDATE_PATHS.setdefault(idoltype.PlatformType.Android, [])
        if package_path not in extra:
            extra.append(package_path)

        # The manga back-side retains honoka-chan's stock wv_ba_01 catalogue
        # key.  These aliases are only a fallback for direct raw-file requests;
        # the data-transfer front cover is installed through 4_0_999.zip.
        mapping = {
            "assets/image/webview/wv_ba_01.png": "npps4_manga.png",
            "assets/image/webview/npps4_manga.png": "npps4_manga.png",
        }
        for client_path, filename in mapping.items():
            local = os.path.join(banner_root, filename).replace("\\", "/")
            _write_if_changed(local, _bundled_asset_bytes("npps4.assets.cn_home_banner", filename))
            _BUNDLED_BANNER_PATHS[client_path] = local
        if _ARCHIVE_ACCESS_MANIFEST:
            _write_if_missing(
                _ARCHIVE_ACCESS_MANIFEST,
                _bundled_asset_bytes("npps4.assets.cn_archive_access", "archive_access_manifest.json"),
            )
    except Exception as exc:
        util.log(
            "CN support assets",
            f"Bundled support materialization failed: {type(exc).__name__}: {exc}",
            severity=util.logging.WARNING,
        )


def initialize():
    global _INITIALIZED, _PACKAGES, _SERVER_INFO_OVERRIDES
    if _INITIALIZED:
        return

    _cleanup_obsolete_museum_transplant_artifacts()
    _ensure_bundled_support_assets()

    for platform, root in _ARCHIVE_DIRS.items():
        if root and not os.path.isdir(root):
            raise RuntimeError(f"CN archive directory is invalid: {root}")
        _PACKAGES[platform] = _scan_platform(platform)

    for platform in _PLATFORM_MAP:
        override = _build_server_info_override(platform)
        if override is not None:
            _SERVER_INFO_OVERRIDES[platform] = override

    # Do not block server startup when the CDN mirror is not present yet. The
    # game server and account database can start independently; clients will get
    # empty download lists until archives are placed in the configured directory.
    _INITIALIZED = True
    try:
        for warning in preflight().get("warnings", []):
            util.log("CN archive preflight warning", warning, severity=util.logging.WARNING)
    except Exception:
        pass
