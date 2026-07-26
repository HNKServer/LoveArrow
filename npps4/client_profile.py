"""Request/session scoped SIF client profile selection.

Only two protocol profiles exist in this fork:

* ``cn``: the 9.7.1 mainland-China client and GHome bootstrap.
* ``gl``: the post-2021 merged JP/EN/Global client family.

The profile is stored in the database session and mirrored in a ContextVar so
legacy code which cannot conveniently accept a context object can still select
the correct master database, release keys and compatibility policy without a
process-global region switch.
"""
from __future__ import annotations

import contextlib
import contextvars
import enum
from typing import Iterator


class ClientProfile(str, enum.Enum):
    CN = "cn"
    GL = "gl"

    @classmethod
    def normalize(cls, value: object, default: "ClientProfile" | None = None) -> "ClientProfile":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower()
        if text in {"cn", "china", "zh", "zh_cn", "zh-cn", "mainland"}:
            return cls.CN
        if text in {"gl", "global", "ww", "en", "jp", "international"}:
            return cls.GL
        if default is not None:
            return default
        raise ValueError(f"unknown client profile: {value!r}")


_CURRENT: contextvars.ContextVar[ClientProfile] = contextvars.ContextVar(
    "npps4_client_profile", default=ClientProfile.GL
)


def current() -> ClientProfile:
    return _CURRENT.get()


def set_current(profile: ClientProfile | str) -> contextvars.Token[ClientProfile]:
    return _CURRENT.set(ClientProfile.normalize(profile))


def reset(token: contextvars.Token[ClientProfile]) -> None:
    _CURRENT.reset(token)


@contextlib.contextmanager
def using(profile: ClientProfile | str) -> Iterator[ClientProfile]:
    normalized = ClientProfile.normalize(profile)
    token = _CURRENT.set(normalized)
    try:
        yield normalized
    finally:
        _CURRENT.reset(token)


def detect(
    *,
    client_version: str | tuple[int, int] | None = None,
    explicit_header: str | None = None,
    request_path: str = "",
    default: ClientProfile = ClientProfile.GL,
) -> ClientProfile:
    """Detect profile before a login session exists.

    The explicit private header is useful for tools/tests. GHome is always CN.
    A 9.x ``Client-Version`` is an APK/application version in the supplied CN
    and GL clients, not the downloadable content version, so it cannot select a
    profile.  The login RSA key and the authenticated token resolve that
    ambiguity later.  Retain the old content-version heuristic only for headers
    which actually look like the 50.x/90.x server-version domains.
    """
    if explicit_header:
        try:
            return ClientProfile.normalize(explicit_header)
        except ValueError:
            pass
    path = str(request_path or "").lower()
    if path.startswith(("/v1/", "/agreement/", "/integration/")):
        return ClientProfile.CN
    if isinstance(client_version, tuple):
        major = int(client_version[0])
    else:
        try:
            major = int(str(client_version or "").split(".", 1)[0])
        except (TypeError, ValueError):
            major = -1
    if major >= 90:
        return ClientProfile.CN
    if 50 <= major < 90:
        return ClientProfile.GL
    # 9.7.1 (CN) and 9.11.x-style merged-client builds are application
    # versions.  Falling back to the operator's default is temporary: authkey
    # immediately replaces it with the profile identified by the RSA key, and
    # all later requests use the signed session token's stored profile.
    return default
