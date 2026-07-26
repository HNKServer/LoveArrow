"""Profile-aware download and master-data backend registry."""
from __future__ import annotations

from typing import Any

import fastapi

from .profile_backend import CustomBackend, InternalBackend, ModuleBackend, N4DLAPIBackend, NoneBackend
from .. import client_profile, idoltype, util
from ..config import config

_BACKENDS: dict[client_profile.ClientProfile, Any] = {}
_ERRORS: dict[client_profile.ClientProfile, str] = {}


def _create(profile: client_profile.ClientProfile):
    settings = config.get_profile_download(profile)
    backend = str(settings.backend).strip().lower()
    if backend == "none":
        return NoneBackend(profile, settings.none)
    if backend == "n4dlapi":
        return N4DLAPIBackend(profile, settings.n4dlapi)
    if backend == "internal":
        return InternalBackend(profile, settings.internal)
    if backend == "cn_archive":
        if profile is not client_profile.ClientProfile.CN:
            raise RuntimeError("cn_archive backend is only valid for CN")
        from . import cn_archive
        return ModuleBackend(profile, cn_archive)
    if backend == "custom":
        return CustomBackend.load(profile, settings.custom.file)
    raise RuntimeError(f"Unknown {profile.value.upper()} download backend: {backend!r}")


def initialize_profiles() -> None:
    _BACKENDS.clear()
    _ERRORS.clear()
    for profile in client_profile.ClientProfile:
        if not config.profile_enabled(profile):
            continue
        try:
            backend = _create(profile)
            # Release-key writes and legacy configuration helpers must observe
            # the backend being initialized, not the process default profile.
            with client_profile.using(profile):
                backend.initialize()
            _BACKENDS[profile] = backend
            util.log(
                "Download profile ready",
                f"profile={profile.value}",
                f"backend={config.get_profile_download(profile).backend}",
                f"version={get_server_version_string(profile)}",
                severity=util.logging.INFO,
            )
        except Exception as exc:
            _ERRORS[profile] = f"{type(exc).__name__}: {exc}"
            util.log(
                "Download profile failed",
                f"profile={profile.value}",
                _ERRORS[profile],
                severity=util.logging.ERROR,
            )
    if not _BACKENDS:
        detail = "; ".join(f"{p.value}: {e}" for p, e in _ERRORS.items()) or "no enabled profile"
        raise RuntimeError(f"No client download profile initialized: {detail}")


def get_backend(profile: client_profile.ClientProfile | str | None = None):
    normalized = client_profile.current() if profile is None else client_profile.ClientProfile.normalize(profile)
    backend = _BACKENDS.get(normalized)
    if backend is None:
        error = _ERRORS.get(normalized, "profile disabled or not initialized")
        raise RuntimeError(f"{normalized.value.upper()} download profile unavailable: {error}")
    return backend


def get_profile_status() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for profile in client_profile.ClientProfile:
        backend = _BACKENDS.get(profile)
        result[profile.value] = {
            "enabled": config.profile_enabled(profile),
            "ready": backend is not None,
            "backend": config.get_profile_download(profile).backend if config.profile_enabled(profile) else "",
            "version": get_server_version_string(profile) if backend is not None else None,
            "error": _ERRORS.get(profile, ""),
        }
    return result


class _CurrentBackendProxy:
    """Compatibility proxy for old code which probes CURRENT_BACKEND methods."""
    def __getattr__(self, name: str):
        return getattr(get_backend(), name)


CURRENT_BACKEND = _CurrentBackendProxy()


def get_server_version(profile: client_profile.ClientProfile | str | None = None):
    return get_backend(profile).get_server_version()


def get_server_version_string(profile: client_profile.ClientProfile | str | None = None):
    backend = get_backend(profile)
    raw = getattr(backend, "get_server_version_string", None)
    return raw() if raw is not None else util.sif_version_string(backend.get_server_version())


def get_db_path(name: str, profile: client_profile.ClientProfile | str | None = None):
    return get_backend(profile).get_db_path(name)


async def get_update_files(
    request: fastapi.Request,
    platform: idoltype.PlatformType,
    from_client_version: tuple[int, int],
    profile: client_profile.ClientProfile | str | None = None,
):
    return await get_backend(profile).get_update_files(request, platform, from_client_version)


async def get_update_files_raw(
    request: fastapi.Request,
    platform: idoltype.PlatformType,
    install_version: str,
    external_version: str,
    profile: client_profile.ClientProfile | str | None = None,
):
    backend = get_backend(profile)
    raw = getattr(backend, "get_update_files_raw", None)
    if raw is not None:
        return await raw(request, platform, install_version, external_version)
    try:
        target = min(util.parse_sif_version(external_version), util.parse_sif_version(install_version))
    except ValueError:
        target = util.parse_sif_version(external_version)
    return await backend.get_update_files(request, platform, target)


async def get_batch_files(
    request: fastapi.Request,
    platform: idoltype.PlatformType,
    package_type: int,
    exclude: list[int],
    profile: client_profile.ClientProfile | str | None = None,
):
    return await get_backend(profile).get_batch_files(request, platform, package_type, exclude)


async def get_single_package(
    request: fastapi.Request,
    platform: idoltype.PlatformType,
    package_type: int,
    package_id: int,
    profile: client_profile.ClientProfile | str | None = None,
):
    return await get_backend(profile).get_single_package(request, platform, package_type, package_id)


async def get_raw_files(
    request: fastapi.Request,
    platform: idoltype.PlatformType,
    files: list[str],
    profile: client_profile.ClientProfile | str | None = None,
):
    return await get_backend(profile).get_raw_files(request, platform, files)


initialize_profiles()
