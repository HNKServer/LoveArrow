import importlib
import os
import runpy
import sys
import types

import Cryptodome.PublicKey.RSA

from . import cfgtype, data

from typing import cast

BUNDLE_DIR: str | None
"""If running under pyinstaller, this will be pointing to sys._MEIPASS"""

if getattr(sys, "frozen", False):
    import multiprocessing

    multiprocessing.freeze_support()
    ROOT_DIR = os.path.normpath(os.path.dirname(sys.executable))
    BUNDLE_DIR = cast(str, sys._MEIPASS)  # type: ignore
else:
    # On Android/Chaquopy the Python package lives in an AssetFinder path,
    # which is not the mutable server workspace and may not contain files
    # addressable by libraries such as Alembic. The Android wrapper sets
    # NPPS4_ROOT_DIR before importing npps4.*, so prefer it when present.
    ROOT_DIR = os.path.normpath(os.environ.get("NPPS4_ROOT_DIR", os.path.dirname(__file__) + "/../.."))
    BUNDLE_DIR = None

os.makedirs(os.path.join(ROOT_DIR, "data"), exist_ok=True)

# ConfigData.model_config is evaluated when npps4.config.data is imported.
# On Android, a premature import can happen before NPPS4_CONFIG is set. Make
# config.py re-assert the current explicit config path before creating the
# settings object so download.backend is read from the workspace config.toml.
_npps4_config_path = os.environ.get("NPPS4_CONFIG")
if _npps4_config_path:
    # Pydantic v2 exposes ConfigData.model_config as a class attribute.
    # On Android we use a Pydantic v1 compatibility layer, where v2-style
    # `model_config = ...` is stored as a model field default instead.  Put
    # the effective settings config in a private attribute which our local
    # pydantic_settings shim reads before instantiating ConfigData.
    _cfg = None
    try:
        _cfg = getattr(data.ConfigData, "model_config")
    except Exception:
        _cfg = None
    if not isinstance(_cfg, dict):
        try:
            _field = getattr(data.ConfigData, "__fields__", {}).get("model_config")
            _cfg = getattr(_field, "default", None)
        except Exception:
            _cfg = None
    if not isinstance(_cfg, dict):
        _cfg = {}
    _cfg = dict(_cfg)
    _cfg["toml_file"] = _npps4_config_path
    try:
        data.ConfigData._settings_config = _cfg
        data.ConfigData.model_config = _cfg
    except Exception:
        pass

CONFIG_DATA = data.ConfigData()

_SERVER_KEY: Cryptodome.PublicKey.RSA.RsaKey
_SERVER_KEYS: list[tuple[str, Cryptodome.PublicKey.RSA.RsaKey]] = []


def _server_key_password():
    key_password = os.environ.get("NPPS_KEY_PASSWORD", CONFIG_DATA.main.server_private_key_password)
    if key_password == "":
        return None
    return key_password


def _rsa_key_fingerprint(key: Cryptodome.PublicKey.RSA.RsaKey) -> tuple[int, int]:
    pub = key.publickey()
    return (int(pub.n), int(pub.e))


def _load_rsa_key_file(path: str, password: str | None):
    with open(path, "rb") as f:
        return Cryptodome.PublicKey.RSA.import_key(f.read(), password)


def _load_server_keys() -> None:
    """Load the primary server RSA key plus optional client-compatibility keys.

    NPPS4 historically used one private key.  For Android compatibility we may
    need to serve both ordinary NPPS4/GL patched clients and honoka-chan/CN
    patched clients at the same time.  /login/authkey tries these keys in order
    and records the one that worked for the session; responses are then signed
    with the matching key so the client-side embedded public key still verifies.
    """
    global _SERVER_KEY, _SERVER_KEYS

    password = _server_key_password()
    primary_path = os.path.join(ROOT_DIR, CONFIG_DATA.main.server_private_key)
    try:
        primary_key = _load_rsa_key_file(primary_path, password)
    except IOError as e:
        raise Exception("Unable to load server private key. Double-check your configuration.") from e

    keys: list[tuple[str, Cryptodome.PublicKey.RSA.RsaKey]] = [("primary", primary_key)]
    seen = {_rsa_key_fingerprint(primary_key)}

    extra_paths: list[str] = []
    env_extra = os.environ.get("NPPS4_EXTRA_SERVER_PRIVATE_KEYS", "")
    if env_extra:
        # Accept both os.pathsep and comma for Android/Kotlin convenience.
        for part in env_extra.replace(",", os.pathsep).split(os.pathsep):
            part = part.strip()
            if part:
                extra_paths.append(part)

    # Bundled compatibility keys.  These file names are intentionally stable so
    # operators can also copy them into an existing workspace manually.
    extra_paths.extend(["honoka_server_key.pem", "npps4_default_server_key.pem"])

    for index, relpath in enumerate(extra_paths):
        path = relpath if os.path.isabs(relpath) else os.path.join(ROOT_DIR, relpath)
        if not os.path.exists(path) or os.path.abspath(path) == os.path.abspath(primary_path):
            continue
        try:
            key = _load_rsa_key_file(path, None)
        except Exception:
            # Compatibility keys are optional; a malformed custom extra key
            # should not prevent the normal server from starting.
            continue
        fp = _rsa_key_fingerprint(key)
        if fp in seen:
            continue
        seen.add(fp)
        label = os.path.splitext(os.path.basename(path))[0] or f"extra_{index}"
        keys.append((label, key))

    _SERVER_KEYS = keys
    _SERVER_KEY = primary_key


_load_server_keys()


def get_data_directory():
    global ROOT_DIR
    return os.path.abspath(os.path.join(ROOT_DIR, CONFIG_DATA.main.data_directory)).replace("\\", "/")


def is_maintenance():
    global ROOT_DIR
    return os.path.isfile(os.path.join(ROOT_DIR, "maintenance.txt"))


def _version_tuple2(version: str) -> tuple[int, int]:
    parts = str(version).strip().split(".")
    if len(parts) < 2:
        raise ValueError('version must contain at least major.minor')
    return int(parts[0]), int(parts[1])


def get_cn_application_version() -> tuple[int, int]:
    """Return the actual CN APK version used for UI/Lua capability gates.

    This must not be derived from the SIF Client-Version header: the supplied
    CN client sends its archive/server version (97.4.6) in that header.
    """
    global CONFIG_DATA
    return _version_tuple2(CONFIG_DATA.download.cn_archive.application_version)


def get_latest_version():
    global CONFIG_DATA
    if CONFIG_DATA.download.backend == "cn_archive":
        return _version_tuple2(CONFIG_DATA.download.cn_archive.client_version)
    if CONFIG_DATA.download.backend == "none":
        return _version_tuple2(CONFIG_DATA.download.none.client_version)
    # The active download backend also exposes a server version, but importing it
    # here would create a circular dependency during bootstrap.
    return (59, 4)


def get_latest_version_string():
    """Return the server/download package version string exposed to clients.

    NPPS4 historically stores versions as a two-part tuple, but the CN 9.7.x
    client/honoka-chan contract uses the exact three-part package version
    ``97.4.6`` in the Server-Version header and download/update payloads.
    Truncating that to ``97.4`` makes the CN client keep believing the 99_*
    update package is not fully applied, so it never reaches the normal bulk
    download stage.
    """
    global CONFIG_DATA
    if CONFIG_DATA.download.backend == "cn_archive":
        return str(CONFIG_DATA.download.cn_archive.client_version).strip()
    if CONFIG_DATA.download.backend == "none":
        return str(CONFIG_DATA.download.none.client_version).strip()
    return "%d.%d" % get_latest_version()


def skip_generic_client_version_check():
    """Whether NPPS4's legacy Client-Version check should be bypassed.

    CN sends the Android application version in the Client-Version header
    (for example 9.7.1) while the download package/server version is 97.4.6.
    honoka-chan does not compare those two values.  Keeping NPPS4's original
    tuple comparison would cause normal post-download game endpoints to return
    an empty response instead of entering the game.
    """
    global CONFIG_DATA
    return CONFIG_DATA.download.backend == "cn_archive" and is_cn_compat()


def get_server_rsa():
    global _SERVER_KEY
    return _SERVER_KEY


def get_server_rsa_candidates():
    global _SERVER_KEYS
    return tuple(_SERVER_KEYS)


def get_server_rsa_by_label(label: str | None):
    global _SERVER_KEYS, _SERVER_KEY
    if label is None:
        return _SERVER_KEY
    for key_label, key in _SERVER_KEYS:
        if key_label == label:
            return key
    return _SERVER_KEY


_SECRET_KEY: bytes = CONFIG_DATA.main.secret_key.encode("UTF-8")


def get_secret_key():
    global _SECRET_KEY
    return _SECRET_KEY


_BASE_XORPAD: bytes = CONFIG_DATA.advanced.base_xorpad.encode("UTF-8")


def get_base_xorpad():
    global _BASE_XORPAD
    return _BASE_XORPAD


_APPLICATION_KEY: bytes = CONFIG_DATA.advanced.application_key.encode("UTF-8")


def get_application_key():
    global _APPLICATION_KEY
    return _APPLICATION_KEY


def need_xmc_verify():
    global CONFIG_DATA
    return CONFIG_DATA.advanced.verify_xmc


def get_database_url():
    global CONFIG_DATA
    return CONFIG_DATA.database.url


def get_consumer_key():
    global CONFIG_DATA
    return CONFIG_DATA.advanced.consumer_key


def inject_server_info():
    global CONFIG_DATA
    return CONFIG_DATA.download.send_patched_server_info


def load_module_from_file(file: str, modulename: str):
    # Android wrapper copies editable external scripts into the app workspace.
    # Prefer the real file when it exists so edits to external/*.py take effect;
    # fall back to the bundled import only when the workspace file is missing.
    if os.path.isfile(file):
        return types.SimpleNamespace(**runpy.run_path(file))
    return importlib.import_module(modulename)


def _protocol_has_callables(module, required: list[str]) -> bool:
    return all(callable(getattr(module, name, None)) for name in required)


def _ensure_protocol(module, modulename: str, required: list[str]):
    if _protocol_has_callables(module, required):
        return module
    return importlib.import_module(modulename)


_LOGIN_BONUS_FILE = os.path.join(ROOT_DIR, CONFIG_DATA.game.login_bonus)
_login_bonus_module = cast(cfgtype.LoginBonusProtocol, load_module_from_file(_LOGIN_BONUS_FILE, "external.login_bonus"))



def is_cn_compat():
    global CONFIG_DATA
    return CONFIG_DATA.compat.region.lower() in {"cn", "china", "zh_cn", "zh"}


def use_cn_headers():
    global CONFIG_DATA
    return is_cn_compat() and CONFIG_DATA.compat.cn_main_headers


def cn_autocreate_ghome_users():
    global CONFIG_DATA
    return is_cn_compat() and CONFIG_DATA.compat.cn_autocreate_ghome_users


def use_cn_wrappers():
    global CONFIG_DATA
    return is_cn_compat() and CONFIG_DATA.compat.cn_wrappers


def use_cn_optional_stubs():
    global CONFIG_DATA
    return is_cn_compat() and CONFIG_DATA.compat.cn_optional_stubs


def get_daily_rotation_timezone_name() -> str:
    global CONFIG_DATA
    name = CONFIG_DATA.compat.daily_rotation_timezone.strip()
    if not name or name.lower() == "auto":
        return "Asia/Shanghai" if is_cn_compat() else "Asia/Tokyo"
    if name.lower() in {"system", "local"}:
        return "local"
    return name


def get_login_bonus_protocol():
    global _login_bonus_module
    # Normal path: external/login_bonus.py must provide async get_rewards().
    # Android v4.29/v4.30 workspaces could contain only a placeholder file;
    # bootstrap should repair it, but keep this validation here so an invalid
    # editable hook is replaced by the bundled default provider instead of
    # breaking /lbonus/execute at runtime.
    if not callable(getattr(_login_bonus_module, "get_rewards", None)):
        _login_bonus_module = cast(cfgtype.LoginBonusProtocol, importlib.import_module("external.login_bonus"))
    return _login_bonus_module


BADWORDS_CHECK_FILE = os.path.join(ROOT_DIR, CONFIG_DATA.game.badwords)
_badwords_check_module = None


async def contains_badwords(string: str, context):
    global _badwords_check_module

    if _badwords_check_module is None:
        _badwords_check_module = cast(
            cfgtype.BadwordsCheckProtocol, load_module_from_file(BADWORDS_CHECK_FILE, "external.badwords")
        )

    _badwords_check_module = _ensure_protocol(_badwords_check_module, "external.badwords", ["has_badwords"])
    return await _badwords_check_module.has_badwords(string, context)


BEATMAP_PROVIDER_FILE = os.path.join(ROOT_DIR, CONFIG_DATA.game.beatmaps)
_beatmap_provider_module = None


def get_beatmap_provider_protocol():
    global _beatmap_provider_module

    if _beatmap_provider_module is None:
        _beatmap_provider_module = cast(
            cfgtype.BeatmapProviderProtocol, load_module_from_file(BEATMAP_PROVIDER_FILE, "external.beatmap")
        )

    _beatmap_provider_module = _ensure_protocol(_beatmap_provider_module, "external.beatmap", ["get_beatmap_data", "randomize_beatmaps"])
    return _beatmap_provider_module


LIVE_UNIT_DROP_FILE = os.path.join(ROOT_DIR, CONFIG_DATA.game.live_unit_drop)
_live_unit_drop_module = None


def get_live_unit_drop_protocol():
    global _live_unit_drop_module

    if _live_unit_drop_module is None:
        _live_unit_drop_module = cast(
            cfgtype.LiveUnitDropProtocol, load_module_from_file(LIVE_UNIT_DROP_FILE, "external.live_unit_drop")
        )

    _live_unit_drop_module = _ensure_protocol(_live_unit_drop_module, "external.live_unit_drop", ["get_live_drop_unit"])
    return _live_unit_drop_module


CUSTOM_DOWNLOAD_FILE = os.path.join(ROOT_DIR, CONFIG_DATA.download.custom.file)
_custom_download_backend_module = None


def get_custom_download_protocol():
    global _custom_download_backend_module

    if _custom_download_backend_module is None:
        _custom_download_backend_module = cast(
            cfgtype.DownloadBackendProtocol,
            load_module_from_file(CUSTOM_DOWNLOAD_FILE, "external.custom_downloader"),
        )

    return _custom_download_backend_module


# HACK: Override script mode
override_script_mode = None


def _override_script_mode(mode: bool):
    global override_script_mode
    override_script_mode = mode


def is_script_mode():
    global override_script_mode
    if override_script_mode is not None:
        return override_script_mode

    # Doing "python -m npps4.script" implicitly loads "npps4" module which loads "npps4.config.config".
    # As per Python documentation, the sys.argv[0] will equal to "-m" if the module is being loaded, however
    # endpoint registration happends during loading.
    return (
        hasattr(sys, "ps1")
        or "npps4.script_dummy" in sys.modules
        or (len(sys.argv) > 0 and (sys.argv[0] == "-m" or "alembic" in sys.argv[0].lower()))
    )


def get_server_data_path():
    return os.path.join(ROOT_DIR, CONFIG_DATA.main.server_data)


LIVE_BOX_DROP_FILE = os.path.join(ROOT_DIR, CONFIG_DATA.game.live_box_drop)
_live_box_drop_module = None


def get_live_box_drop_protocol():
    global _live_box_drop_module

    if _live_box_drop_module is None:
        _live_box_drop_module = cast(
            cfgtype.LiveDropBoxProtocol, load_module_from_file(LIVE_BOX_DROP_FILE, "external.live_box_drop")
        )

    _live_box_drop_module = _ensure_protocol(_live_box_drop_module, "external.live_box_drop", ["process_effort_box"])
    return _live_box_drop_module


def get_session_expiry_time():
    global CONFIG_DATA
    return CONFIG_DATA.main.session_expiry


def is_account_export_enabled():
    global CONFIG_DATA
    return CONFIG_DATA.iex.enable_export


def store_backup_of_notes_list():
    global CONFIG_DATA
    return CONFIG_DATA.main.save_notes_list


def get_live_continue_loveca_cost() -> int:
    global CONFIG_DATA
    return max(CONFIG_DATA.compat.live_continue_loveca_cost, 0)



def reload_runtime_editable_data() -> dict[str, object]:
    """Reload Android-editable config/data hooks without rebuilding FastAPI routes.

    This is intentionally a partial hot reload: it refreshes config.toml-derived
    scalar values and reloads editable external/*.py protocols. It does not move
    the running listening socket or rebuild already-registered routes; changing
    host/port, database URL, or download backend still requires a restart.
    """
    global CONFIG_DATA, _SERVER_KEY, _SECRET_KEY, _BASE_XORPAD, _APPLICATION_KEY
    global _LOGIN_BONUS_FILE, _login_bonus_module
    global BADWORDS_CHECK_FILE, _badwords_check_module
    global BEATMAP_PROVIDER_FILE, _beatmap_provider_module
    global LIVE_UNIT_DROP_FILE, _live_unit_drop_module
    global LIVE_BOX_DROP_FILE, _live_box_drop_module
    global CUSTOM_DOWNLOAD_FILE, _custom_download_backend_module

    cfg_path = os.environ.get("NPPS4_CONFIG")
    if cfg_path:
        cfg = dict(getattr(data.ConfigData, "model_config", {}) or {})
        cfg["toml_file"] = cfg_path
        try:
            data.ConfigData._settings_config = cfg
            data.ConfigData.model_config = cfg
        except Exception:
            pass

    CONFIG_DATA = data.ConfigData()

    _SECRET_KEY = CONFIG_DATA.main.secret_key.encode("UTF-8")
    _BASE_XORPAD = CONFIG_DATA.advanced.base_xorpad.encode("UTF-8")
    _APPLICATION_KEY = CONFIG_DATA.advanced.application_key.encode("UTF-8")

    _load_server_keys()

    _LOGIN_BONUS_FILE = os.path.join(ROOT_DIR, CONFIG_DATA.game.login_bonus)
    _login_bonus_module = cast(cfgtype.LoginBonusProtocol, load_module_from_file(_LOGIN_BONUS_FILE, "external.login_bonus"))

    BADWORDS_CHECK_FILE = os.path.join(ROOT_DIR, CONFIG_DATA.game.badwords)
    _badwords_check_module = None

    BEATMAP_PROVIDER_FILE = os.path.join(ROOT_DIR, CONFIG_DATA.game.beatmaps)
    _beatmap_provider_module = None

    LIVE_UNIT_DROP_FILE = os.path.join(ROOT_DIR, CONFIG_DATA.game.live_unit_drop)
    _live_unit_drop_module = None

    LIVE_BOX_DROP_FILE = os.path.join(ROOT_DIR, CONFIG_DATA.game.live_box_drop)
    _live_box_drop_module = None

    CUSTOM_DOWNLOAD_FILE = os.path.join(ROOT_DIR, CONFIG_DATA.download.custom.file)
    _custom_download_backend_module = None

    return {
        "ok": True,
        "server_data": get_server_data_path(),
        "login_bonus": _LOGIN_BONUS_FILE,
        "badwords": BADWORDS_CHECK_FILE,
        "beatmaps": BEATMAP_PROVIDER_FILE,
        "live_unit_drop": LIVE_UNIT_DROP_FILE,
        "live_box_drop": LIVE_BOX_DROP_FILE,
    }
