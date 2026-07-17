"""CN compatibility audit helpers.

These endpoints do not change gameplay. They make it visible whether the running
server is using NPPS4-native behavior, honoka-compatible adapters, or temporary
stubs for CN-specific protocol stages.
"""

from __future__ import annotations

import importlib
import os
import zipfile
from typing import Any

import fastapi.responses

from .app import app
from .config import config


DOWNLOAD_EXPECTATIONS: list[dict[str, Any]] = [
    {
        "route": "/main.php/download/update",
        "cn_rule": "honoka-compatible update stage: compare exact package version string such as 97.4.6; if outdated, return 99_0_* update packages plus the CN server_info override package; do not inject NPPS4 JP/GL dynamic /server_info/{hash}.",
        "npps4_risk": "NPPS4's original two-component version parsing and JP-encrypted server_info package can make the CN client finish a download but crash or re-enter an empty update stage.",
        "current_adapter": "npps4.download.cn_archive.get_update_files_raw",
    },
    {
        "route": "/main.php/download/event",
        "cn_rule": "honoka-compatible no-op: accept any request body and return an empty list.",
        "npps4_risk": "Using the batch request schema here can reject valid CN module/action/timeStamp-shaped event requests before the handler runs.",
        "current_adapter": "permissive DownloadEventRequest in npps4.game.download",
    },
    {
        "route": "/main.php/download/batch",
        "cn_rule": "honoka-compatible batch stage: only return data when client_version exactly matches the CN package version; package_type 0 maps to 4 for the first full/basic download size flow.",
        "npps4_risk": "Returning package data regardless of client_version can put the CN native download state machine into a branch different from honoka-chan.",
        "current_adapter": "npps4.game.download + npps4.download.cn_archive.get_batch_files",
    },
    {
        "route": "/main.php/download/additional",
        "cn_rule": "honoka-compatible package lookup: package_type + package_id + target_os maps directly to raw <type>_<id>_<order>.zip files.",
        "npps4_risk": "Pydantic request models must accept CN object aliases and must not assume NPPS4 internal archive-root layout.",
        "current_adapter": "npps4.download.cn_archive.get_single_package",
    },
    {
        "route": "/main.php/download/getUrl",
        "cn_rule": "honoka-compatible extracted-file lookup: path_list items become CDN/extracted URLs with path separators normalized.",
        "npps4_risk": "Without android_extracted/ios_extracted, the client can pass download stages but later 404 on on-demand story/assets.",
        "current_adapter": "npps4.download.cn_archive.get_raw_files",
    },
]

CRITICAL_COMPAT_AREAS: list[dict[str, str]] = [
    {
        "area": "Client/server/package version separation",
        "required_cn_behavior": "Treat APK Client-Version (for example 9.7.1), package version (97.4.6), and 99_0_* update package order as separate concepts.",
        "do_not_do": "Do not truncate CN package version to NPPS4's historical major.minor tuple, and do not compare APK Client-Version against 97.4.6.",
    },
    {
        "area": "CN server_info override",
        "required_cn_behavior": "Serve a CN-encrypted honoka-shaped 99_0_115.zip override generated from a real 99_0_* template and containing root server_info.json; patch domain/api_uri dynamically to the actual request host so the game layer cannot fall back to prod.game1.ll.sdo.com.",
        "do_not_do": "Do not use NPPS4's JP/GL dynamic config/server_info.json injection for cn_archive.",
    },
    {
        "area": "Request parsing",
        "required_cn_behavior": "Accept CN request aliases and object-shaped package references at the adapter boundary, then translate into NPPS4 core models.",
        "do_not_do": "Do not weaken NPPS4 core state with random dicts; do not let strict Pydantic models reject a known CN transport shape before an adapter sees it.",
    },
    {
        "area": "GHome/Shengqu SDK",
        "required_cn_behavior": "Bridge SDK account state into normal NPPS4 users and keep CN SDK responses shape-compatible with GHome.",
        "do_not_do": "Do not treat every CN SDK endpoint as a harmless 200 OK if the response controls later game-login state.",
    },
    {
        "area": "Gameplay endpoints",
        "required_cn_behavior": "Prefer NPPS4 as source of truth, with CN response adapters only where field shape differs.",
        "do_not_do": "Do not copy honoka's simplified all-unlocked/account-progress behavior over NPPS4 unless the existing NPPS4 state model cannot support the client.",
    },
]


def _zip_has(path: str, name: str) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            names = {n.replace('\\', '/') for n in zf.namelist()}
            return name in names
    except Exception:
        return False


def _cn_archive_preflight() -> dict[str, Any]:
    if config.CONFIG_DATA.download.backend != "cn_archive":
        return {"backend": config.CONFIG_DATA.download.backend, "enabled": False}
    try:
        backend = importlib.import_module("npps4.download.cn_archive")
        info = backend.preflight()
        # Add server_info path-specific checks which caused several CN failures.
        override_info = info.get("server_info_override") if isinstance(info, dict) else None
        if isinstance(override_info, dict):
            for platform, data in override_info.items():
                if isinstance(data, dict):
                    local_path = str(data.get("local_path") or "")
                    data["configured_has_root_server_info_json"] = bool(local_path and os.path.isfile(local_path) and _zip_has(local_path, "server_info.json"))
                    data["configured_has_config_server_info_json"] = bool(local_path and os.path.isfile(local_path) and _zip_has(local_path, "config/server_info.json"))
        materialized = {}
        for key, pkg in getattr(backend, "_SERVER_INFO_MATERIALIZED", {}).items():
            platform, base_url = key
            local_path = str(getattr(pkg, "local_path", "") or "")
            materialized[f"{platform}:{base_url}"] = {
                "local_path": local_path,
                "filename": getattr(pkg, "filename", ""),
                "has_root_server_info_json": bool(local_path and os.path.isfile(local_path) and _zip_has(local_path, "server_info.json")),
                "has_config_server_info_json": bool(local_path and os.path.isfile(local_path) and _zip_has(local_path, "config/server_info.json")),
            }
        info["server_info_materialized"] = materialized
        return info
    except Exception as exc:
        return {"backend": "cn_archive", "enabled": True, "error": f"{type(exc).__name__}: {exc}"}


@app.core.get("/npps4/cn-compat-audit.json")
async def cn_compat_audit_endpoint():
    cfg = config.CONFIG_DATA
    return fastapi.responses.JSONResponse(
        {
            "region": cfg.compat.region,
            "download_backend": cfg.download.backend,
            "cn_main_headers": cfg.compat.cn_main_headers,
            "cn_wrappers": cfg.compat.cn_wrappers,
            "cn_optional_stubs": cfg.compat.cn_optional_stubs,
            "send_patched_server_info": cfg.download.send_patched_server_info,
            "critical_areas": CRITICAL_COMPAT_AREAS,
            "download_expectations": DOWNLOAD_EXPECTATIONS,
            "cn_archive_preflight": _cn_archive_preflight(),
        }
    )


@app.core.get("/npps4/cn-preflight.json")
async def cn_preflight_endpoint():
    try:
        from .tools.cn_compat_preflight import run_cn_preflight
        return fastapi.responses.JSONResponse(run_cn_preflight())
    except Exception as exc:
        return fastapi.responses.JSONResponse(
            status_code=500,
            content={"error": f"{type(exc).__name__}: {exc}"},
        )
