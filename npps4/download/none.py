"""Deprecated process-global download backend compatibility shim.

NPPS4 v5 selects download/master sources through ``npps4.download.download``
using the request/session ClientProfile.  This module is retained only for old
operator scripts which imported the former backend module directly.
"""
from __future__ import annotations

from . import download as _registry


def initialize():
    # Backends are initialized once by the profile registry.
    return None


def get_server_version():
    return _registry.get_server_version()


def get_server_version_string():
    return _registry.get_server_version_string()


def get_db_path(name: str):
    return _registry.get_db_path(name)


async def get_update_files(request, platform, from_client_version):
    return await _registry.get_update_files(request, platform, from_client_version)


async def get_update_files_raw(request, platform, install_version, external_version):
    return await _registry.get_update_files_raw(request, platform, install_version, external_version)


async def get_batch_files(request, platform, package_type, exclude):
    return await _registry.get_batch_files(request, platform, package_type, exclude)


async def get_single_package(request, platform, package_type, package_id):
    return await _registry.get_single_package(request, platform, package_type, package_id)


async def get_raw_files(request, platform, files):
    return await _registry.get_raw_files(request, platform, files)
