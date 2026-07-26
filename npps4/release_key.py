from __future__ import annotations

from . import client_profile

_RELEASE_KEYS: dict[client_profile.ClientProfile, dict[int, str]] = {
    client_profile.ClientProfile.CN: {},
    client_profile.ClientProfile.GL: {},
}


def _bucket(profile: client_profile.ClientProfile | str | None = None) -> dict[int, str]:
    p = client_profile.current() if profile is None else client_profile.ClientProfile.normalize(profile)
    return _RELEASE_KEYS.setdefault(p, {})


def get(key: int, default=None, profile: client_profile.ClientProfile | str | None = None):
    return _bucket(profile).get(key, default)


def update(values: dict[int, str], profile: client_profile.ClientProfile | str | None = None):
    _bucket(profile).update(values)


def clear(profile: client_profile.ClientProfile | str | None = None):
    _bucket(profile).clear()


def formatted(profile: client_profile.ClientProfile | str | None = None):
    return [{"id": k, "key": v} for k, v in sorted(_bucket(profile).items())]
