from __future__ import annotations

import itsdangerous

from ..config import config

_SALT = "npps4-cn-transfer-web-v1"
_MAX_AGE = 24 * 60 * 60


def _serializer() -> itsdangerous.URLSafeTimedSerializer:
    return itsdangerous.URLSafeTimedSerializer(config.CONFIG_DATA.main.secret_key, salt=_SALT)


def make_token(user_id: int) -> str:
    return _serializer().dumps({"user_id": int(user_id)})


def load_token(token: str) -> int:
    try:
        data = _serializer().loads(token, max_age=_MAX_AGE)
        return int(data["user_id"])
    except (itsdangerous.BadData, KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid or expired transfer page token") from exc
