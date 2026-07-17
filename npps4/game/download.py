import enum

from .. import idol
from .. import idoltype
from .. import svinfo
from .. import util
from ..config import config
from ..download import download
from ..idol import error

import pydantic

_TARGET_OS_REMAP = {"Android": idoltype.PlatformType.Android, "iOS": idoltype.PlatformType.iOS}


class DownloadTargetOS(str, enum.Enum):
    ANDROID = "Android"
    IPHONE = "iOS"


class DownloadPackageType(enum.IntEnum):
    BOOTSTRAP = 0
    LIVE = 1
    SCENARIO = 2
    SUBSCENARIO = 3
    MICRO = 4
    EVENT_SCENARIO = 5
    MULTI_UNIT_SCENARIO = 6


class DownloadPackageRef(pydantic.BaseModel):
    """CN 9.7.x sends package_list entries as objects, while NPPS4/GL can use ints.

    honoka-chan treats the field as []any and ignores it for update selection.
    NPPS4 only needs the package_id values when it does look at a package list,
    so normalize both shapes at the request-model boundary instead of weakening
    the download backend itself.
    """

    model_config = pydantic.ConfigDict(extra="allow")

    package_id: int
    package_type: int | None = None


def _normalize_package_id_list(value):
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        return value
    out: list[int] = []
    for item in value:
        if isinstance(item, dict):
            if "package_id" in item:
                out.append(int(item["package_id"]))
            elif "id" in item:
                out.append(int(item["id"]))
            else:
                # Let Pydantic raise a useful validation error instead of
                # silently accepting an unrecognizable object.
                out.append(item)
        elif isinstance(item, DownloadPackageRef):
            out.append(int(item.package_id))
        else:
            out.append(item)
    return out


def _normalize_package_id(value):
    if isinstance(value, dict):
        for key in ("package_id", "id", "packageId"):
            if key in value:
                return int(value[key])
    if isinstance(value, DownloadPackageRef):
        return int(value.package_id)
    return value


def _normalize_path_list(value):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return value
    out: list[str] = []
    for item in value:
        if isinstance(item, dict):
            picked = None
            for key in ("path", "file", "file_path", "filepath", "name", "asset_path", "url"):
                if key in item and item[key] not in (None, ""):
                    picked = str(item[key])
                    break
            out.append(picked if picked is not None else item)
        else:
            out.append(item)
    return out


class DownloadUpdateRequest(pydantic.BaseModel):
    target_os: DownloadTargetOS
    install_version: str
    external_version: str
    package_list: list[int] = pydantic.Field(default_factory=list)

    @pydantic.field_validator("package_list", mode="before")
    @classmethod
    def _accept_cn_package_list_objects(cls, value):
        return _normalize_package_id_list(value)


class DownloadBatchRequest(pydantic.BaseModel):
    client_version: str
    os: DownloadTargetOS
    package_type: DownloadPackageType
    excluded_package_ids: list[int] = pydantic.Field(default_factory=list)

    @pydantic.field_validator("excluded_package_ids", mode="before")
    @classmethod
    def _accept_cn_excluded_package_objects(cls, value):
        return _normalize_package_id_list(value)


class DownloadEventRequest(pydantic.BaseModel):
    """Permissive request shape for /download/event.

    honoka-chan ignores the request body for this action and always returns an
    empty list.  The CN client may send module/action/timeStamp fields rather
    than NPPS4's batch-shaped client_version/os/package_type fields.  Keeping
    the old DownloadBatchRequest here turns a harmless compatibility no-op into
    an HTTP/Pydantic validation failure.
    """

    model_config = pydantic.ConfigDict(extra="allow")


class DownloadAdditionalRequest(pydantic.BaseModel):
    target_os: DownloadTargetOS
    package_type: DownloadPackageType
    package_id: int

    @pydantic.field_validator("package_id", mode="before")
    @classmethod
    def _accept_cn_package_object(cls, value):
        return _normalize_package_id(value)


class DownloadInfo(pydantic.BaseModel):
    size: str
    url: str


class DownloadUpdateInfo(DownloadInfo):
    version: str


class DownloadGetUrlRequest(pydantic.BaseModel):
    os: DownloadTargetOS
    path_list: list[str]

    @pydantic.field_validator("path_list", mode="before")
    @classmethod
    def _accept_cn_path_objects(cls, value):
        return _normalize_path_list(value)


class DownloadGetUrlResponse(pydantic.BaseModel):
    url_list: list[str]


class DownloadCommonResponse(pydantic.RootModel[list[DownloadInfo]]):
    pass


class DownloadUpdateResponse(pydantic.RootModel[list[DownloadUpdateInfo]]):
    pass


@idol.register("download", "update", check_version=False, batchable=False)
async def download_update(context: idol.SchoolIdolAuthParams, request: DownloadUpdateRequest) -> DownloadUpdateResponse:
    # Get download links. CN 9.7.x must keep the exact 3-part package-version
    # string (97.4.6); truncating it through NPPS4's historical 2-part tuple
    # makes the client believe the update never finished.
    platform = _TARGET_OS_REMAP[request.target_os.value]
    if config.CONFIG_DATA.download.backend == "cn_archive":
        links = await download.get_update_files_raw(
            context.request, platform, request.install_version, request.external_version
        )
    else:
        try:
            install_version = util.parse_sif_version(request.install_version)
            external_version = util.parse_sif_version(request.external_version)
            target_version = min(external_version, install_version)
        except ValueError as e:
            raise error.IdolError(detail=str(e))
        links = await download.get_update_files(context.request, platform, target_version)
    result = [DownloadUpdateInfo(url=link.url, size=str(link.size), version=link.version) for link in links]

    # Inject autogenerated server info for JP/GL-style clients only.
    # CN clients use a different encrypted file format/key schedule for
    # config/server_info.json.  Feeding them NPPS4's old JP-encrypted dynamic
    # server_info ZIP is dangerous: the download can complete, but the next
    # launch crashes inside libGame.so's encrypt/File.cpp path while reading the
    # cached server_info package.  The cn_archive backend instead replaces
    # 99_0_115.zip with a prepared CN-compatible encrypted override.
    if config.inject_server_info() and config.CONFIG_DATA.download.backend != "cn_archive":
        filehash, size = svinfo.generate_server_info(context.request, download.get_server_version())
        target_version_str = util.sif_version_string(download.get_server_version())
        result.append(
            DownloadUpdateInfo(
                url=str(context.request.url_for("server_info", filehash=filehash)),
                size=str(size),
                version=target_version_str,
            )
        )

    return DownloadUpdateResponse.model_validate(result)


@idol.register("download", "batch", check_version=False, batchable=False)
async def download_batch(context: idol.SchoolIdolAuthParams, request: DownloadBatchRequest) -> DownloadCommonResponse:
    if config.CONFIG_DATA.download.backend == "cn_archive":
        expected = download.get_server_version_string() if hasattr(download.CURRENT_BACKEND, "get_server_version_string") else None
        if expected and str(request.client_version or "").strip() != expected:
            util.log(
                "CN download/batch",
                f"client_version={request.client_version!r} expected={expected!r}; returning 0 packages like honoka-chan",
                severity=util.logging.INFO,
            )
            return DownloadCommonResponse.model_validate([])

    links = await download.get_batch_files(
        context.request, _TARGET_OS_REMAP[request.os.value], int(request.package_type), request.excluded_package_ids
    )
    return DownloadCommonResponse.model_validate([DownloadInfo(url=link.url, size=str(link.size)) for link in links])


@idol.register("download", "event", check_version=False, batchable=False)
async def download_event(context: idol.SchoolIdolAuthParams, request: DownloadEventRequest) -> DownloadCommonResponse:
    # honoka-chan ignores this request body and returns an empty list.  Keep the
    # same behavior, but do not force NPPS4's batch request model onto CN.
    return DownloadCommonResponse.model_validate([])


@idol.register("download", "additional", check_version=False, batchable=False)
async def download_additional(
    context: idol.SchoolIdolAuthParams, request: DownloadAdditionalRequest
) -> DownloadCommonResponse:
    links = await download.get_single_package(
        context.request, _TARGET_OS_REMAP[request.target_os.value], int(request.package_type), request.package_id
    )
    if links is None:
        raise error.IdolError(error.ERROR_DOWNLOAD_NO_ADDITIONAL_PACKAGE)
    return DownloadCommonResponse.model_validate([DownloadInfo(url=link.url, size=str(link.size)) for link in links])


@idol.register("download", "getUrl", check_version=False, batchable=False)
async def download_geturl(context: idol.SchoolIdolAuthParams, request: DownloadGetUrlRequest) -> DownloadGetUrlResponse:
    links = await download.get_raw_files(context.request, _TARGET_OS_REMAP[request.os.value], request.path_list)
    return DownloadGetUrlResponse(url_list=[link.url for link in links])
