import fastapi

from . import none as none_backend

from .. import idoltype
from .. import util
from ..config import config, cfgtype

from typing import Callable


def n4dlapi_factory():
    from . import n4dlapi as n4dlapi_backend

    return n4dlapi_backend


def internal_factory():
    from . import internal as internal_backend

    return internal_backend


def cn_archive_factory():
    from . import cn_archive as cn_archive_backend

    return cn_archive_backend


BACKEND_FACTORY: dict[str, Callable[[], cfgtype.DownloadBackendProtocol]] = {
    "none": lambda: none_backend,
    "n4dlapi": n4dlapi_factory,
    "internal": internal_factory,
    "cn_archive": cn_archive_factory,
    "custom": config.get_custom_download_protocol,
}
assert config.CONFIG_DATA.download.backend is not None
_used_backend = BACKEND_FACTORY.get(config.CONFIG_DATA.download.backend)
if _used_backend is None:
    raise Exception(f"Missing or unknown backend '{config.CONFIG_DATA.download.backend}'")

CURRENT_BACKEND = _used_backend()


def get_server_version():
    global CURRENT_BACKEND
    assert CURRENT_BACKEND is not None
    return CURRENT_BACKEND.get_server_version()


def get_server_version_string():
    global CURRENT_BACKEND
    assert CURRENT_BACKEND is not None
    raw_func = getattr(CURRENT_BACKEND, "get_server_version_string", None)
    if raw_func is not None:
        return raw_func()
    return util.sif_version_string(CURRENT_BACKEND.get_server_version())


def get_db_path(name: str):
    global CURRENT_BACKEND
    assert CURRENT_BACKEND is not None
    return CURRENT_BACKEND.get_db_path(name)


async def get_update_files(
    request: fastapi.Request, platform: idoltype.PlatformType, from_client_version: tuple[int, int]
):
    global CURRENT_BACKEND
    assert CURRENT_BACKEND is not None
    return await CURRENT_BACKEND.get_update_files(request, platform, from_client_version)


async def get_update_files_raw(
    request: fastapi.Request, platform: idoltype.PlatformType, install_version: str, external_version: str
):
    global CURRENT_BACKEND
    assert CURRENT_BACKEND is not None
    raw_func = getattr(CURRENT_BACKEND, "get_update_files_raw", None)
    if raw_func is not None:
        return await raw_func(request, platform, install_version, external_version)
    try:
        install = util.parse_sif_version(install_version)
        external = util.parse_sif_version(external_version)
        target = min(external, install)
    except ValueError:
        target = util.parse_sif_version(external_version)
    return await CURRENT_BACKEND.get_update_files(request, platform, target)


async def get_batch_files(
    request: fastapi.Request, platform: idoltype.PlatformType, package_type: int, exclude: list[int]
):
    global CURRENT_BACKEND
    assert CURRENT_BACKEND is not None
    return await CURRENT_BACKEND.get_batch_files(request, platform, package_type, exclude)


async def get_single_package(
    request: fastapi.Request, platform: idoltype.PlatformType, package_type: int, package_id: int
):
    global CURRENT_BACKEND
    assert CURRENT_BACKEND is not None
    return await CURRENT_BACKEND.get_single_package(request, platform, package_type, package_id)


async def get_raw_files(request: fastapi.Request, platform: idoltype.PlatformType, files: list[str]):
    global CURRENT_BACKEND
    assert CURRENT_BACKEND is not None
    return await CURRENT_BACKEND.get_raw_files(request, platform, files)


CURRENT_BACKEND.initialize()
