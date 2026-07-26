# When editing this, please synchronize the changes with config.sample.toml (and your own config.toml).
import os
import re

import pydantic
import pydantic_settings

from typing import Annotated

_VERSION_TEST = re.compile(r"^\d+\.\d+(?:\.\d+)?$")


def _test_version_string(v: str):
    if re.match(_VERSION_TEST, v) is None:
        raise ValueError('"client_version" must be in form of "major.minor" or "major.minor.patch".')
    return v


def _test_length(l: int):
    def inner(v: str):
        nonlocal l
        if len(v) != l:
            raise ValueError(f"the length must be {l}")
        return v

    return inner


class _Main(pydantic.BaseModel):
    data_directory: Annotated[
        str, pydantic.Field(validation_alias=pydantic.AliasChoices("data_directory", "datadir"))
    ] = "data"
    secret_key: Annotated[str, pydantic.Field(validation_alias=pydantic.AliasChoices("secret_key", "secretkey"))] = (
        "Hello World"
    )
    server_private_key: Annotated[
        str, pydantic.Field(validation_alias=pydantic.AliasChoices("server_private_key", "pkey"))
    ] = "default_server_key.pem"
    server_private_key_password: Annotated[
        str, pydantic.Field(validation_alias=pydantic.AliasChoices("server_private_key_password", "pkeypass"))
    ] = ""
    server_data: Annotated[str, pydantic.Field(validation_alias=pydantic.AliasChoices("server_data", "serverdata"))] = (
        "npps4/server_data.json"
    )
    session_expiry: Annotated[
        int, pydantic.Field(validation_alias=pydantic.AliasChoices("session_expiry", "tokenexpiry"))
    ] = 259200
    save_notes_list: Annotated[
        int, pydantic.Field(validation_alias=pydantic.AliasChoices("save_notes_list", "savenoteslist"))
    ] = False


class _Database(pydantic.BaseModel):
    url: str = "sqlite+aiosqlite:///data/main.sqlite3"


class _DownloadNone(pydantic.BaseModel):
    client_version: Annotated[
        str,
        pydantic.Field(validation_alias=pydantic.AliasChoices("client_version", "version")),
        pydantic.AfterValidator(_test_version_string),
    ] = "59.4"


class _DownloadNPPS4DLAPI(pydantic.BaseModel):
    server: str = ""
    shared_key: Annotated[str, pydantic.Field(validation_alias=pydantic.AliasChoices("shared_key", "key"))] = ""


class _DownloadInternal(pydantic.BaseModel):
    archive_root: Annotated[str, pydantic.Field(validation_alias=pydantic.AliasChoices("archive_root", "root"))] = ""


class _DownloadCNArchive(pydantic.BaseModel):
    # Flat archive directories as used by the CN client/honoka-chan, e.g.
    # list_CN_Android/1_578_1.zip.  Paths are relative to project root unless
    # absolute.
    android_archives: str = ""
    ios_archives: str = ""
    android_extracted: str = ""
    ios_extracted: str = ""
    db_root: str = ""
    # Android APK version used only for client capability gates.  It is
    # intentionally separate from the 97.4.6 archive/content version below.
    application_version: Annotated[str, pydantic.AfterValidator(_test_version_string)] = "9.7.1"
    client_version: Annotated[str, pydantic.AfterValidator(_test_version_string)] = "97.4.6"
    update_package_type: int = 99
    server_info_override: str = "99_0_115.zip"
    # Optional prepared replacement ZIPs.  If set, the backend serves these
    # files as `server_info_override` instead of the archive-directory copy.
    # This is useful for CN clients because config/server_info.json inside the
    # ZIP is encrypted; operators usually prepare it once with libhonoka and
    # let the server append it as the final 99-package.
    android_server_info_override: str = ""
    ios_server_info_override: str = ""
    # Optional GL/JP CDN overlay used only when a CN extracted asset is absent.
    # CN updates, package versions and databases continue to come from cn_archive.
    gl_overlay_enabled: bool = True
    gl_overlay_server: str = "https://ll.sif.moe/npps4_dlapi"
    gl_overlay_shared_key: str = ""
    gl_overlay_cache: str = ""
    gl_overlay_timeout: float = 30.0
    gl_overlay_try_language_fallback: bool = True
    gl_overlay_negative_ttl: int = 300
    # Optional locally generated CN update packages.  These are appended to the
    # normal flat archive list without changing the retained CN content version.
    android_extra_update_packages: list[str] = pydantic.Field(default_factory=list)
    ios_extra_update_packages: list[str] = pydantic.Field(default_factory=list)
    archive_access_manifest: str = "data/cn_update_overlays/archive_access_manifest.json"
    # normal | all.  This is strictly the native CN Museum catalogue (16 rows);
    # the deprecated museum_bridge_unlock_policy name is accepted only so old
    # operator configs keep their intended all-unlock behavior.
    museum_unlock_policy: Annotated[
        str,
        pydantic.Field(validation_alias=pydantic.AliasChoices(
            "museum_unlock_policy", "museum_bridge_unlock_policy"
        )),
    ] = "all"
    main_scenario_unlock_policy: str = "normal"
    subscenario_unlock_policy: str = "normal"
    live_unlock_policy: str = "normal"
    # normal | archive | all | complete.  all/complete create Album catalog
    # rows only; complete also marks Album progression flags.
    album_catalog_unlock_policy: str = "normal"


class _DownloadCustom(pydantic.BaseModel):
    file: str = ""


class _ProfileDownload(pydantic.BaseModel):
    """Independent download/master source for one client profile."""

    enabled: bool = False
    backend: str = ""
    send_patched_server_info: bool = True
    # normal | all. Applies only to this profile's native Museum catalogue.
    museum_unlock_policy: str = "all"
    none: _DownloadNone = pydantic.Field(default_factory=_DownloadNone)
    n4dlapi: _DownloadNPPS4DLAPI = pydantic.Field(default_factory=_DownloadNPPS4DLAPI)
    internal: _DownloadInternal = pydantic.Field(default_factory=_DownloadInternal)
    cn_archive: _DownloadCNArchive = pydantic.Field(default_factory=_DownloadCNArchive)
    custom: _DownloadCustom = pydantic.Field(default_factory=_DownloadCustom)

    @pydantic.model_validator(mode="before")
    @classmethod
    def migrate_nested_museum_policy(cls, value):
        """Accept the v4.60-v5.04 CN-only nested policy without losing it."""
        if isinstance(value, dict) and "museum_unlock_policy" not in value:
            nested = value.get("cn_archive")
            if isinstance(nested, dict):
                legacy = nested.get("museum_unlock_policy", nested.get("museum_bridge_unlock_policy"))
                if legacy is not None:
                    value = dict(value)
                    value["museum_unlock_policy"] = legacy
        return value


class _DownloadProfiles(pydantic.BaseModel):
    cn: _ProfileDownload = pydantic.Field(default_factory=_ProfileDownload)
    gl: _ProfileDownload = pydantic.Field(default_factory=_ProfileDownload)


class _Download(pydantic.BaseModel):
    # Legacy v4.60 fields remain readable.  When profiles.* is absent the
    # validator below migrates this single backend to the matching profile.
    backend: str = ""
    send_patched_server_info: Annotated[
        bool, pydantic.Field(validation_alias=pydantic.AliasChoices("send_patched_server_info", "fixserverinfo"))
    ] = True
    none: _DownloadNone = pydantic.Field(default_factory=_DownloadNone)
    n4dlapi: _DownloadNPPS4DLAPI = pydantic.Field(default_factory=_DownloadNPPS4DLAPI)
    internal: _DownloadInternal = pydantic.Field(default_factory=_DownloadInternal)
    cn_archive: _DownloadCNArchive = pydantic.Field(default_factory=_DownloadCNArchive)
    custom: _DownloadCustom = pydantic.Field(default_factory=_DownloadCustom)

    default_profile: str = "cn"
    profiles: _DownloadProfiles = pydantic.Field(default_factory=_DownloadProfiles)

    @pydantic.model_validator(mode="after")
    def migrate_legacy_backend(self):
        cn = self.profiles.cn
        gl = self.profiles.gl
        if not cn.enabled and not gl.enabled and self.backend:
            target = cn if self.backend == "cn_archive" else gl
            target.enabled = True
            target.backend = self.backend
            target.send_patched_server_info = self.send_patched_server_info
            target.none = self.none
            target.n4dlapi = self.n4dlapi
            target.internal = self.internal
            target.cn_archive = self.cn_archive
            target.museum_unlock_policy = self.cn_archive.museum_unlock_policy
            target.custom = self.custom
            self.default_profile = "cn" if target is cn else "gl"
        return self


class _Game(pydantic.BaseModel):
    badwords: str = "external/badwords.py"
    login_bonus: Annotated[str, pydantic.Field(validation_alias=pydantic.AliasChoices("login_bonus", "loginbonus"))] = (
        "external/login_bonus.py"
    )
    beatmaps: str = "external/beatmap.py"
    live_unit_drop: Annotated[
        str, pydantic.Field(validation_alias=pydantic.AliasChoices("live_unit_drop", "unitdrop"))
    ] = "external/live_unit_drop.py"
    live_box_drop: Annotated[
        str, pydantic.Field(validation_alias=pydantic.AliasChoices("live_box_drop", "boxdrop"))
    ] = "external/live_box_drop.py"


class _Advanced(pydantic.BaseModel):
    base_xorpad: Annotated[
        str,
        pydantic.Field(validation_alias=pydantic.AliasChoices("base_xorpad", "basekey")),
        pydantic.AfterValidator(_test_length(32)),
    ] = "eit4Ahph4aiX4ohmephuobei6SooX9xo"
    application_key: Annotated[
        str,
        pydantic.Field(validation_alias=pydantic.AliasChoices("application_key", "appkey")),
        pydantic.AfterValidator(_test_length(32)),
    ] = "b6e6c940a93af2357ea3e0ace0b98afc"
    consumer_key: Annotated[
        str, pydantic.Field(validation_alias=pydantic.AliasChoices("consumer_key", "consumerkey"))
    ] = "lovelive_test"
    verify_xmc: Annotated[bool, pydantic.Field(validation_alias=pydantic.AliasChoices("verify_xmc", "xmc"))] = True


class _Compat(pydantic.BaseModel):
    # Deprecated v4.x process-global selector.  It remains readable so old
    # config files validate, but request/session ClientProfile is authoritative.
    region: str = "dual"
    # Do not add extra /main.php headers by default. This is not part of NPPS4
    # gameplay logic and should only be enabled when a CN client capture proves
    # it is necessary. GHome responses are handled separately.
    cn_main_headers: bool = False
    cn_autocreate_ghome_users: bool = True
    # Safe wrappers translate CN-only action names into NPPS4's own system layer.
    # These are enabled by default because they preserve NPPS4 gameplay state.
    cn_wrappers: bool = True
    # Optional safety-net stubs for CN-only endpoints. Disabled by default so
    # missing features stay visible instead of being silently papered over.
    cn_optional_stubs: bool = False
    # Timezone used for date-bound CN compatibility features such as daily
    # special-live rotation and random-live attribute rotation. Use an IANA
    # name. "auto" means Asia/Shanghai for CN profile and Asia/Tokyo
    # otherwise. This is a timezone conversion, not a manual +8h offset.
    daily_rotation_timezone: str = "auto"
    # Loveca cost for live/continue and rlive/continue. SIF1-style continue
    # consumes one Loveca by default while keeping the in-progress live session.
    live_continue_loveca_cost: int = 1


class _ImportExport(pydantic.BaseModel):
    enable_export: Annotated[
        bool, pydantic.Field(validation_alias=pydantic.AliasChoices("enable_export", "export"))
    ] = False
    enable_import: Annotated[
        bool, pydantic.Field(validation_alias=pydantic.AliasChoices("enable_import", "import"))
    ] = False
    bypass_signature: Annotated[
        bool, pydantic.Field(validation_alias=pydantic.AliasChoices("bypass_signature", "bypass"))
    ] = False


class _Gameplay(pydantic.BaseModel):
    energy_multiplier: Annotated[
        float, pydantic.Field(validation_alias=pydantic.AliasChoices("energy_multiplier", "lpmul"))
    ] = 1
    love_multiplier: Annotated[
        float, pydantic.Field(validation_alias=pydantic.AliasChoices("love_multiplier", "lovemul"))
    ] = 1
    secretbox_cost_multiplier: Annotated[
        float, pydantic.Field(validation_alias=pydantic.AliasChoices("secretbox_cost_multiplier", "gachacostmul"))
    ] = 1
    # Museum/Album unlocks remain visible, but their permanent Smile/Pure/Cool
    # bonuses are disabled by default so CN and GL share the same scoring
    # foundation. Operators may explicitly re-enable the regional bonus.
    museum_stat_bonus_enabled: Annotated[
        bool, pydantic.Field(validation_alias=pydantic.AliasChoices(
            "museum_stat_bonus_enabled", "museumstats"
        ))
    ] = False


class ConfigData(pydantic_settings.BaseSettings):
    model_config = pydantic_settings.SettingsConfigDict(
        env_prefix="NPPS4_CONFIG_",
        env_nested_delimiter="_",
        toml_file=os.environ.get("NPPS4_CONFIG", "config.toml"),
        nested_model_default_partial_update=True,
    )

    main: _Main = pydantic.Field(default_factory=_Main)
    database: _Database = pydantic.Field(default_factory=_Database)
    download: _Download = pydantic.Field(default_factory=_Download)
    game: _Game = pydantic.Field(default_factory=_Game)
    gameplay: _Gameplay = pydantic.Field(default_factory=_Gameplay)
    compat: _Compat = pydantic.Field(default_factory=_Compat)
    advanced: _Advanced = pydantic.Field(default_factory=_Advanced)
    iex: _ImportExport = pydantic.Field(default_factory=_ImportExport)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[pydantic_settings.BaseSettings],
        init_settings: pydantic_settings.PydanticBaseSettingsSource,
        env_settings: pydantic_settings.PydanticBaseSettingsSource,
        dotenv_settings: pydantic_settings.PydanticBaseSettingsSource,
        file_secret_settings: pydantic_settings.PydanticBaseSettingsSource,
    ) -> tuple[pydantic_settings.PydanticBaseSettingsSource, ...]:
        return env_settings, dotenv_settings, pydantic_settings.TomlConfigSettingsSource(settings_cls)

    @pydantic.model_validator(mode="after")
    def check_download_mode_sane(self):
        enabled = []
        for profile_name in ("cn", "gl"):
            profile = getattr(self.download.profiles, profile_name)
            if not profile.enabled:
                continue
            enabled.append(profile_name)
            backend = profile.backend
            if backend == "none":
                pass
            elif backend == "n4dlapi":
                if not profile.n4dlapi.server:
                    raise ValueError(f"{profile_name.upper()} NPPS4 DLAPI missing server")
            elif backend == "internal":
                if not profile.internal.archive_root:
                    raise ValueError(f"{profile_name.upper()} missing archive-root directory")
            elif backend == "custom":
                if not profile.custom.file:
                    raise ValueError(f"{profile_name.upper()} missing custom downloader script")
            elif backend == "cn_archive":
                if profile_name != "cn":
                    raise ValueError("cn_archive is only valid for the CN profile")
                if not (profile.cn_archive.android_archives or profile.cn_archive.ios_archives):
                    raise ValueError("Missing CN archive directory")
            else:
                raise ValueError(f"Unknown {profile_name.upper()} download backend: {backend!r}")

        if not enabled:
            raise ValueError("At least one CN/GL client profile must be enabled")
        if self.download.default_profile not in enabled:
            self.download.default_profile = enabled[0]
        return self


__all__ = ["ConfigData"]
