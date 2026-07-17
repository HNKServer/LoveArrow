"""Generic Honky v4 file encryption/decryption for SIF1 master data.

NPPS4's CN server-info helper intentionally remains separate because it also
supports the older CN v3 header and key table.  Museum master files in the CN
9.7.1 and community/WW clients use Honky v4, whose stream state only depends on
region name-prefix, basename, header LCG selector and file bytes.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

NAME_PREFIXES: dict[str, bytes] = {
    "jp": b"Hello",
    "ww": b"BFd3EnkcKa",
    "cn": b"iLbs0LpvJrXm3zjdhAr4",
}

_V4_LCG_PARAM = (
    (1103515245, 12345, 15),
    (22695477, 1, 23),
    (214013, 2531011, 24),
    (65793, 4282663, 8),
)


@dataclass(frozen=True)
class HonkyV4Meta:
    region: str
    filename: str
    lcg_index: int


def _prefix(region: str) -> bytes:
    key = str(region).lower().strip()
    try:
        return NAME_PREFIXES[key]
    except KeyError as exc:
        raise ValueError(f"unsupported Honky region: {region!r}") from exc


def _md5(region: str, filename: str | bytes) -> tuple[bytes, bytes]:
    filename_b = filename.encode("utf-8") if isinstance(filename, str) else filename
    basename = os.path.basename(filename_b)
    h = hashlib.md5(_prefix(region), usedforsecurity=False)
    h.update(basename)
    return h.digest(), basename


def _header_matches(data: bytes, region: str, filename: str) -> bool:
    if len(data) < 16:
        return False
    md5, _ = _md5(region, filename)
    return (
        data[0] == ((~md5[4]) & 0xFF)
        and data[1] == ((~md5[5]) & 0xFF)
        and data[2] == ((~md5[6]) & 0xFF)
        and data[7] == 2
        and 0 <= data[6] < len(_V4_LCG_PARAM)
    )


def detect_v4(data: bytes, filename: str, region: str | None = None) -> HonkyV4Meta:
    candidates = [region] if region else list(NAME_PREFIXES)
    for candidate in candidates:
        if candidate is not None and _header_matches(data, candidate, filename):
            return HonkyV4Meta(region=str(candidate).lower(), filename=filename, lcg_index=int(data[6]))
    requested = f" for region {region!r}" if region else ""
    raise ValueError(f"invalid or unsupported Honky v4 header for {filename!r}{requested}")


def _crypt(data: bytes, meta: HonkyV4Meta) -> bytes:
    md5, _ = _md5(meta.region, meta.filename)
    idx = int(meta.lcg_index)
    if idx < 0 or idx >= len(_V4_LCG_PARAM):
        raise ValueError(f"invalid Honky v4 LCG index: {idx}")
    a, c, shift = _V4_LCG_PARAM[idx]
    state = (md5[8] << 24) | (md5[9] << 16) | (md5[10] << 8) | md5[11]
    out = bytearray(len(data))
    for i, value in enumerate(data):
        out[i] = value ^ ((state >> (shift & 0x1F)) & 0xFF)
        state = (state * a + c) & 0xFFFFFFFF
    return bytes(out)


def decrypt_v4(data: bytes, filename: str, region: str | None = None) -> tuple[bytes, HonkyV4Meta]:
    meta = detect_v4(data, filename, region)
    return _crypt(data[16:], meta), meta


def _emit_header(meta: HonkyV4Meta) -> bytes:
    md5, _ = _md5(meta.region, meta.filename)
    return bytes(
        [
            (~md5[4]) & 0xFF,
            (~md5[5]) & 0xFF,
            (~md5[6]) & 0xFF,
            12,
            0,
            0,
            int(meta.lcg_index) & 0xFF,
            2,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ]
    )


def encrypt_v4(plaintext: bytes, meta: HonkyV4Meta, filename: str | None = None) -> bytes:
    target = HonkyV4Meta(
        region=meta.region,
        filename=filename or meta.filename,
        lcg_index=meta.lcg_index,
    )
    return _emit_header(target) + _crypt(plaintext, target)
