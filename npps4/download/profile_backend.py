"""Independent download/master backends for CN and GL profiles."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import urllib.parse
from pathlib import Path
from typing import Any

import fastapi
import fastapi.staticfiles
import httpx
import pydantic

from . import dltype
from .. import client_profile, idoltype, release_key, util
from ..app import app
from ..config import config


class NoneBackend:
    def __init__(self, profile: client_profile.ClientProfile, settings):
        self.profile = profile
        self.settings = settings

    def initialize(self) -> None:
        return None

    def get_server_version(self):
        return util.parse_sif_version(self.settings.client_version)

    def get_server_version_string(self) -> str:
        return str(self.settings.client_version)

    def get_db_path(self, name: str) -> str:
        # CN content versions retain a third component (97.4.6).  The legacy
        # tuple formatter intentionally models only major/minor and would turn
        # that directory into 97.4, making a valid local CN master invisible.
        raw_ver = self.get_server_version_string().strip()
        parsed_ver = util.sif_version_string(self.get_server_version())
        versions = tuple(dict.fromkeys((raw_ver, parsed_ver)))
        base = config.get_data_directory()
        candidates = tuple(
            path
            for ver in versions
            for path in (
                f"{base}/db/{self.profile.value}/{ver}/{name}.db_",
                f"{base}/db/{ver}/{name}.db_",
            )
        ) + (
            f"{base}/db/{self.profile.value}/{name}.db_",
            f"{base}/db/{name}.db_",
        )
        for path in candidates:
            if os.path.isfile(path):
                return path
        raise RuntimeError(f"Database {name!r} not found for {self.profile.value}: {candidates}")

    async def get_update_files(self, request, platform, from_client_version):
        return []

    async def get_update_files_raw(self, request, platform, install_version, external_version):
        return []

    async def get_batch_files(self, request, platform, package_type, exclude):
        return []

    async def get_single_package(self, request, platform, package_type, package_id):
        return None

    async def get_raw_files(self, request: fastapi.Request, platform, files):
        target = str(request.url).rstrip("/") + "/missing"
        empty = dltype.Checksum(
            md5=hashlib.md5(b"").hexdigest(),
            sha256=hashlib.sha256(b"").hexdigest(),
        )
        return [dltype.BaseInfo(url=target, size=0, checksums=empty) for _ in files]


class N4DLAPIBackend:
    NEED_PROTOCOL_VERSION = (1, 1)
    UpdateAdapter = pydantic.TypeAdapter(list[dltype.UpdateInfo])
    BatchAdapter = pydantic.TypeAdapter(list[dltype.BatchInfo])
    BaseAdapter = pydantic.TypeAdapter(list[dltype.BaseInfo])

    def __init__(self, profile: client_profile.ClientProfile, settings):
        self.profile = profile
        self.base_url = str(settings.server).rstrip("/") + "/"
        self.shared_key = str(settings.shared_key or "")
        self.public_info: dict[str, Any] = {}

    def _url(self, endpoint: str) -> str:
        return urllib.parse.urljoin(self.base_url, endpoint.lstrip("/"))

    def _headers(self, request_data=None) -> dict[str, str]:
        result: dict[str, str] = {}
        if self.shared_key:
            result["DLAPI-Shared-Key"] = urllib.parse.quote(self.shared_key)
        if request_data is not None:
            result["Content-Type"] = "application/json"
        return result

    def _call(self, endpoint: str, request_data=None, *, raw: bool = False):
        last: Exception | None = None
        for _ in range(25):
            try:
                response = httpx.request(
                    "GET" if request_data is None else "POST",
                    self._url(endpoint),
                    headers=self._headers(request_data),
                    json=request_data,
                    timeout=30,
                )
                response.raise_for_status()
                return response.content if raw else response.json()
            except (json.JSONDecodeError, httpx.HTTPStatusError):
                raise
            except Exception as exc:
                last = exc
        assert last is not None
        raise last

    async def _call_async(self, endpoint: str, request_data=None, *, raw: bool = False):
        last: Exception | None = None
        async with httpx.AsyncClient(timeout=30) as http:
            for _ in range(25):
                try:
                    response = await http.request(
                        "GET" if request_data is None else "POST",
                        self._url(endpoint),
                        headers=self._headers(request_data),
                        json=request_data,
                    )
                    response.raise_for_status()
                    return response.content if raw else response.json()
                except (json.JSONDecodeError, httpx.HTTPStatusError):
                    raise
                except Exception as exc:
                    last = exc
        assert last is not None
        raise last

    @staticmethod
    def _fixup_links(links, platform: idoltype.PlatformType):
        for link in links:
            if link.url.startswith("https://") and int(platform) == 2:
                link.url = "http" + link.url[5:]
        return links

    def initialize(self):
        util.log("Initializing DLAPI", f"profile={self.profile.value}", f"server={self.base_url}")
        self.public_info = self._call("api/publicinfo")
        protocol = self.public_info["dlapiVersion"]
        if protocol["major"] != self.NEED_PROTOCOL_VERSION[0] or protocol["minor"] < self.NEED_PROTOCOL_VERSION[1]:
            raise RuntimeError(f"DLAPI for {self.profile.value} is too old: {protocol}")
        keys = {int(k): v for k, v in self._call("api/v1/release_info").items()}
        release_key.update(keys, profile=self.profile)

    def get_server_version(self):
        if not self.public_info:
            raise RuntimeError(f"DLAPI backend {self.profile.value} is not initialized")
        return util.parse_sif_version(self.public_info["gameVersion"])

    def get_server_version_string(self):
        return str(self.public_info["gameVersion"])

    def get_db_path(self, name: str):
        version = util.sif_version_string(self.get_server_version())
        target = Path(config.get_data_directory()) / "db" / self.profile.value / version / f"{name}.db_"
        if not target.is_file():
            util.log("Downloading master DB", f"profile={self.profile.value}", f"name={name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(self._call(f"api/v1/getdb/{name}", raw=True))
        return str(target)

    async def get_update_files(self, request, platform, from_client_version):
        raw = await self._call_async(
            "api/v1/update", {"version": util.sif_version_string(from_client_version), "platform": int(platform)}
        )
        return self._fixup_links(self.UpdateAdapter.validate_python(raw), platform)

    async def get_update_files_raw(self, request, platform, install_version, external_version):
        try:
            version = min(util.parse_sif_version(install_version), util.parse_sif_version(external_version))
        except ValueError:
            version = util.parse_sif_version(external_version)
        return await self.get_update_files(request, platform, version)

    async def get_batch_files(self, request, platform, package_type, exclude):
        raw = await self._call_async(
            "api/v1/batch", {"package_type": package_type, "platform": int(platform), "exclude": exclude}
        )
        return self._fixup_links(self.BatchAdapter.validate_python(raw), platform)

    async def get_single_package(self, request, platform, package_type, package_id):
        try:
            raw = await self._call_async(
                "api/v1/download",
                {"package_type": package_type, "package_id": package_id, "platform": int(platform)},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                return None
            raise
        return self._fixup_links(self.BaseAdapter.validate_python(raw), platform)

    async def get_raw_files(self, request, platform, files):
        raw = await self._call_async("api/v1/getfile", {"files": files, "platform": int(platform)})
        return self._fixup_links(self.BaseAdapter.validate_python(raw), platform)


class _MemoizeByModTime:
    def __init__(self, func):
        self.func = func
        self.map: dict[str, tuple[int, Any]] = {}

    def __call__(self, path: str):
        stat = os.stat(path)
        cached = self.map.get(path)
        if cached and stat.st_mtime_ns <= cached[0]:
            return cached[1]
        result = self.func(path)
        self.map[path] = (stat.st_mtime_ns, result)
        return result


@_MemoizeByModTime
def _read_json(path: str):
    with open(path, "r", encoding="UTF-8") as stream:
        return json.load(stream)


@_MemoizeByModTime
def _get_versions(path: str):
    result = []
    for value in _read_json(path):
        try:
            result.append(util.parse_sif_version(value))
        except ValueError:
            pass
    return sorted(result)


class InternalBackend:
    NEED_GENERATION = (1, 1)
    PLATFORM_MAP = ["iOS", "Android"]

    def __init__(self, profile: client_profile.ClientProfile, settings):
        self.profile = profile
        self.root = str(settings.archive_root).replace("\\", "/").rstrip("/")
        self.route_name = f"archive_root_{profile.value}"
        self.mount_path = f"/archive-root-{profile.value}"

    def initialize(self):
        if not os.path.isdir(self.root):
            raise RuntimeError(f"{self.profile.value.upper()} archive root is invalid: {self.root}")
        generation_path = os.path.join(self.root, "generation.json")
        generation = _read_json(generation_path) if os.path.isfile(generation_path) else {"major": 1, "minor": 0}
        if generation["major"] != self.NEED_GENERATION[0] or generation["minor"] < self.NEED_GENERATION[1]:
            raise RuntimeError(f"{self.profile.value.upper()} archive generation is out of date")
        release_info = _read_json(os.path.join(self.root, "release_info.json"))
        release_key.update({int(k): v for k, v in release_info.items()}, profile=self.profile)
        app.core.mount(
            self.mount_path,
            fastapi.staticfiles.StaticFiles(directory=self.root),
            self.route_name,
        )

    def get_server_version(self):
        for platform in self.PLATFORM_MAP:
            target = f"{self.root}/{platform}/package/info.json"
            if os.path.isfile(target):
                return _get_versions(target)[-1]
        raise RuntimeError(f"No packages found in {self.root}")

    def get_server_version_string(self):
        return util.sif_version_string(self.get_server_version())

    def get_db_path(self, name: str):
        version = self.get_server_version_string()
        for platform in self.PLATFORM_MAP:
            path = f"{self.root}/{platform}/package/{version}/db/{name}.db_"
            if os.path.isfile(path):
                return path
        raise RuntimeError(f"Database {name!r} not found for {self.profile.value}")

    def _url(self, request: fastapi.Request, relative: str) -> str:
        return str(request.url_for(self.route_name, path=relative))

    async def get_update_files(self, request, platform, from_client_version):
        platform_name = self.PLATFORM_MAP[int(platform) - 1]
        base = f"{self.root}/{platform_name}/update"
        versions = _get_versions(base + "/infov2.json")
        result = []
        if versions and from_client_version == versions[-1]:
            return result
        for version in (value for value in versions if value > from_client_version):
            version_text = util.sif_version_string(version)
            for info in _read_json(f"{base}/{version_text}/infov2.json"):
                result.append(dltype.UpdateInfo(
                    url=self._url(request, f"{platform_name}/update/{version_text}/{info['name']}"),
                    size=info["size"],
                    checksums=dltype.Checksum(md5=info["md5"], sha256=info["sha256"]),
                    version=version_text,
                ))
        return result

    async def get_update_files_raw(self, request, platform, install_version, external_version):
        try:
            version = min(util.parse_sif_version(install_version), util.parse_sif_version(external_version))
        except ValueError:
            version = util.parse_sif_version(external_version)
        return await self.get_update_files(request, platform, version)

    async def get_batch_files(self, request, platform, package_type, exclude):
        platform_name = self.PLATFORM_MAP[int(platform) - 1]
        version = self.get_server_version_string()
        base = f"{self.root}/{platform_name}/package/{version}/{package_type}"
        result = []
        for package_id in sorted(set(_read_json(base + "/info.json")).difference(exclude)):
            for info in _read_json(f"{base}/{package_id}/infov2.json"):
                result.append(dltype.BatchInfo(
                    url=self._url(request, f"{platform_name}/package/{version}/{package_type}/{package_id}/{info['name']}"),
                    size=info["size"],
                    checksums=dltype.Checksum(md5=info["md5"], sha256=info["sha256"]),
                    packageId=package_id,
                ))
        return result

    async def get_single_package(self, request, platform, package_type, package_id):
        platform_name = self.PLATFORM_MAP[int(platform) - 1]
        version = self.get_server_version_string()
        relative = f"{platform_name}/package/{version}/{package_type}/{package_id}"
        base = f"{self.root}/{relative}"
        if not os.path.isdir(base):
            return None
        return [dltype.BaseInfo(
            url=self._url(request, f"{relative}/{info['name']}"),
            size=info["size"],
            checksums=dltype.Checksum(md5=info["md5"], sha256=info["sha256"]),
        ) for info in _read_json(base + "/infov2.json")]

    async def get_raw_files(self, request, platform, files):
        platform_name = self.PLATFORM_MAP[int(platform) - 1]
        version = self.get_server_version_string()
        relative = f"{platform_name}/package/{version}/microdl"
        mapping = _read_json(f"{self.root}/{relative}/info.json")
        result = []
        for requested in files:
            sanitized = os.path.normpath(str(requested).replace("..", "")).replace("\\", "/").lstrip("/")
            info = mapping.get(sanitized, {})
            result.append(dltype.BaseInfo(
                url=self._url(request, f"{relative}/{sanitized}"),
                size=info.get("size", 0),
                checksums=dltype.Checksum(md5=info.get("md5", ""), sha256=info.get("sha256", "")),
            ))
        return result


class ModuleBackend:
    """Adapter around the one CN-specific archive module."""
    def __init__(self, profile, module):
        self.profile = profile
        self.module = module

    def __getattr__(self, name):
        return getattr(self.module, name)


class CustomBackend(ModuleBackend):
    @classmethod
    def load(cls, profile: client_profile.ClientProfile, filename: str):
        path = config.get_absolute_file(filename)
        spec = importlib.util.spec_from_file_location(f"npps4_custom_download_{profile.value}", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load custom backend: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return cls(profile, module)
