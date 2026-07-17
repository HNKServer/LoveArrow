"""Optional GL/JP NPPS4-DLAPI overlay for missing CN extracted assets.

The CN 9.7.1 archive remains authoritative for updates, package lists, versioning,
and databases.  This module is only consulted when a file requested through
``/cn-extracted/<platform>/...`` does not exist in the configured CN extracted
folder.  The missing single file is fetched through NPPS4-DLAPI ``getfile``,
verified, cached locally, and then served from this NPPS4 instance.

This avoids pointing the CN client at a GL download backend wholesale, which
would mix the incompatible 97.4.6 CN content version with the 59.4 GL version.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx

from .. import idoltype, util
from ..config import config

_EMPTY_MD5 = hashlib.md5(b"").hexdigest()
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_PLATFORM_NAME = {
    idoltype.PlatformType.iOS: "iOS",
    idoltype.PlatformType.Android: "Android",
}


@dataclass(frozen=True)
class OverlayInfo:
    requested_path: str
    remote_path: str
    url: str
    size: int
    md5: str
    sha256: str


_cfg = config.CONFIG_DATA.download.cn_archive
_enabled = bool(getattr(_cfg, "gl_overlay_enabled", False))
_base_url = str(getattr(_cfg, "gl_overlay_server", "") or "").strip().rstrip("/") + "/"
_shared_key = str(getattr(_cfg, "gl_overlay_shared_key", "") or "")
_timeout = max(float(getattr(_cfg, "gl_overlay_timeout", 30.0)), 3.0)
_try_language_fallback = bool(getattr(_cfg, "gl_overlay_try_language_fallback", True))
_negative_ttl = max(int(getattr(_cfg, "gl_overlay_negative_ttl", 300)), 0)

_cache_setting = str(getattr(_cfg, "gl_overlay_cache", "") or "").strip()
if _cache_setting:
    _cache_root = (
        os.path.abspath(_cache_setting)
        if os.path.isabs(_cache_setting)
        else os.path.abspath(os.path.join(config.ROOT_DIR, _cache_setting))
    )
else:
    _cache_root = os.path.join(config.get_data_directory(), "gl_overlay_cache")
_cache_root = _cache_root.replace("\\", "/")

_metadata: dict[tuple[int, str], OverlayInfo | None] = {}
_negative_at: dict[tuple[int, str], float] = {}
_locks: dict[tuple[int, str], asyncio.Lock] = {}
_stats = {"hits": 0, "downloads": 0, "not_found": 0, "errors": 0, "bytes": 0}


def enabled() -> bool:
    return _enabled and bool(_base_url)


def cache_root() -> str:
    return _cache_root


def _headers(*, json_body: bool = False) -> dict[str, str]:
    headers: dict[str, str] = {}
    if _shared_key:
        headers["DLAPI-Shared-Key"] = urllib.parse.quote(_shared_key)
    if json_body:
        headers["Content-Type"] = "application/json"
    return headers


def _api_url(endpoint: str) -> str:
    return urllib.parse.urljoin(_base_url, endpoint.lstrip("/"))


def _sanitize(path: str) -> str:
    normalized = os.path.normpath(path.replace("\\", "/")).replace("\\", "/").lstrip("/")
    if normalized in ("", ".") or normalized.startswith("../") or "/../" in f"/{normalized}/":
        raise ValueError("unsafe overlay path")
    return normalized


def _candidate_paths(path: str) -> list[str]:
    path = _sanitize(path)
    candidates = [path]
    if _try_language_fallback:
        if path.startswith("en/"):
            candidates.append(path[3:])
        elif path.startswith("assets/"):
            candidates.append("en/" + path)
    return list(dict.fromkeys(candidates))


def _cache_path(platform: idoltype.PlatformType, path: str) -> str:
    platform_name = _PLATFORM_NAME[platform]
    safe = _sanitize(path)
    target = os.path.abspath(os.path.join(_cache_root, platform_name, safe)).replace("\\", "/")
    root = os.path.abspath(os.path.join(_cache_root, platform_name)).replace("\\", "/")
    if not target.startswith(root + "/"):
        raise ValueError("unsafe overlay cache path")
    return target


def cached_file(platform: idoltype.PlatformType, path: str) -> str | None:
    try:
        target = _cache_path(platform, path)
    except ValueError:
        return None
    return target if os.path.isfile(target) else None


async def _post_getfile(platform: idoltype.PlatformType, files: list[str]) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=_timeout, follow_redirects=True) as client:
        response = await client.post(
            _api_url("api/v1/getfile"),
            headers=_headers(json_body=True),
            json={"files": files, "platform": int(platform)},
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, list) or len(data) != len(files):
            raise RuntimeError("NPPS4-DLAPI getfile returned an unexpected response shape")
        return data


def _parse_info(requested: str, remote: str, raw: dict[str, Any]) -> OverlayInfo | None:
    size = int(raw.get("size", 0) or 0)
    checksums = raw.get("checksums") or {}
    md5 = str(checksums.get("md5", "") or "").lower()
    sha256 = str(checksums.get("sha256", "") or "").lower()
    url = str(raw.get("url", "") or "")
    if size <= 0 or not url or (md5 == _EMPTY_MD5 and sha256 == _EMPTY_SHA256):
        return None
    return OverlayInfo(requested, remote, url, size, md5, sha256)


async def describe_many(
    platform: idoltype.PlatformType, paths: list[str]
) -> dict[str, OverlayInfo | None]:
    result: dict[str, OverlayInfo | None] = {}
    if not enabled() or not paths:
        return {path: None for path in paths}

    now = time.monotonic()
    pending: list[str] = []
    candidate_map: dict[str, list[str]] = {}
    all_candidates: list[str] = []

    for raw_path in paths:
        try:
            path = _sanitize(raw_path)
        except ValueError:
            result[raw_path] = None
            continue
        key = (int(platform), path)
        cached = _metadata.get(key, ...)
        if cached is not ...:
            if cached is not None or now - _negative_at.get(key, 0) < _negative_ttl:
                result[raw_path] = cached
                continue
        pending.append(raw_path)
        candidates = _candidate_paths(path)
        candidate_map[raw_path] = candidates
        all_candidates.extend(candidates)

    if not pending:
        return result

    unique_candidates = list(dict.fromkeys(all_candidates))
    try:
        rows = await _post_getfile(platform, unique_candidates)
        remote_result = {
            candidate: _parse_info(candidate, candidate, row)
            for candidate, row in zip(unique_candidates, rows, strict=True)
        }
    except Exception as exc:
        _stats["errors"] += 1
        util.log("GL overlay getfile failed", type(exc).__name__, str(exc), severity=util.logging.WARNING)
        for raw_path in pending:
            result[raw_path] = None
        return result

    for raw_path in pending:
        safe = _sanitize(raw_path)
        chosen: OverlayInfo | None = None
        for candidate in candidate_map[raw_path]:
            remote = remote_result.get(candidate)
            if remote is not None:
                chosen = OverlayInfo(safe, candidate, remote.url, remote.size, remote.md5, remote.sha256)
                break
        key = (int(platform), safe)
        _metadata[key] = chosen
        if chosen is None:
            _negative_at[key] = time.monotonic()
            _stats["not_found"] += 1
        result[raw_path] = chosen
    return result


async def describe(platform: idoltype.PlatformType, path: str) -> OverlayInfo | None:
    return (await describe_many(platform, [path])).get(path)


async def materialize(platform: idoltype.PlatformType, path: str) -> str | None:
    if not enabled():
        return None
    try:
        safe = _sanitize(path)
    except ValueError:
        return None
    existing = cached_file(platform, safe)
    if existing:
        _stats["hits"] += 1
        return existing

    key = (int(platform), safe)
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        existing = cached_file(platform, safe)
        if existing:
            _stats["hits"] += 1
            return existing
        info = await describe(platform, safe)
        if info is None:
            return None

        target = _cache_path(platform, safe)
        temp = target + ".part"
        os.makedirs(os.path.dirname(target), exist_ok=True)
        try:
            md5_hash = hashlib.md5()
            sha256_hash = hashlib.sha256()
            size = 0
            async with httpx.AsyncClient(timeout=_timeout, follow_redirects=True) as client:
                async with client.stream("GET", info.url) as response:
                    response.raise_for_status()
                    with open(temp, "wb") as out:
                        async for chunk in response.aiter_bytes():
                            if not chunk:
                                continue
                            out.write(chunk)
                            size += len(chunk)
                            md5_hash.update(chunk)
                            sha256_hash.update(chunk)
            if size != info.size:
                raise RuntimeError(f"size mismatch: expected {info.size}, got {size}")
            if info.md5 and md5_hash.hexdigest().lower() != info.md5:
                raise RuntimeError("MD5 mismatch")
            if info.sha256 and sha256_hash.hexdigest().lower() != info.sha256:
                raise RuntimeError("SHA256 mismatch")
            os.replace(temp, target)
            _stats["downloads"] += 1
            _stats["bytes"] += size
            util.log(
                "GL overlay cached",
                f"platform={_PLATFORM_NAME[platform]} requested={safe} remote={info.remote_path} size={size}",
                severity=util.logging.INFO,
            )
            return target
        except Exception as exc:
            _stats["errors"] += 1
            try:
                os.remove(temp)
            except OSError:
                pass
            util.log(
                "GL overlay download failed",
                f"path={safe}",
                type(exc).__name__,
                str(exc),
                severity=util.logging.WARNING,
            )
            return None
        finally:
            _locks.pop(key, None)


def status() -> dict[str, Any]:
    return {
        "enabled": enabled(),
        "server": _base_url,
        "cache_root": _cache_root,
        "try_language_fallback": _try_language_fallback,
        "metadata_entries": len(_metadata),
        "stats": dict(_stats),
    }
