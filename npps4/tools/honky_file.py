"""Honky v3/v4 file encryption helpers for SIF1 client/master files.

The post-merge JP/GL client still uses Honky v3 for selected bootstrap files
such as ``config/server_info.json`` while later master databases use v4.  CN
has a separate legacy helper for its additional v3 variants; this module keeps
portable JP/GL and v4 support in one small, dependency-free implementation.

The v3 algorithm and JP/GL key table follow DarkEnergyProcessor/honky-py
(MIT), with the implementation written locally to keep the source package
self-contained.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

NAME_PREFIXES: dict[str, bytes] = {
    "jp": b"Hello",
    "gl": b"Hello",  # post-merge JP/WW client
    "ww": b"BFd3EnkcKa",
    "cn": b"iLbs0LpvJrXm3zjdhAr4",
}

# Post-merge JP/GL Honky v3 key table.
KEY_TABLES_JP: tuple[int, ...] = (
    1210253353, 1736710334, 1030507233, 1924017366, 1603299666, 1844516425,
    1102797553, 32188137, 782633907, 356258523, 957120135, 10030910,
    811467044, 1226589197, 1303858438, 1423840583, 756169139, 1304954701,
    1723556931, 648430219, 1560506399, 1987934810, 305677577, 505363237,
    450129501, 1811702731, 2146795414, 842747461, 638394899, 51014537,
    198914076, 120739502, 1973027104, 586031952, 1484278592, 1560111926,
    441007634, 1006001970, 2038250142, 232546121, 827280557, 1307729428,
    775964996, 483398502, 1724135019, 2125939248, 742088754, 1411519905,
    136462070, 1084053905, 2039157473, 1943671327, 650795184, 151139993,
    1467120569, 1883837341, 1249929516, 382015614, 1020618905, 1082135529,
    870997426, 1221338057, 1623152467, 1020681319,
)
assert len(KEY_TABLES_JP) == 64

_V4_LCG_PARAM = (
    (1103515245, 12345, 15),
    (22695477, 1, 23),
    (214013, 2531011, 24),
    (65793, 4282663, 8),
)


@dataclass(frozen=True)
class HonkyV3Meta:
    region: str
    filename: str
    name_sum: int
    flipped: bool = False


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


def _v3_table(region: str) -> tuple[int, ...]:
    key = str(region).lower().strip()
    if key in {"jp", "gl"}:
        return KEY_TABLES_JP
    raise ValueError(f"Honky v3 key table is not bundled for region {region!r}")


def _header_signature_matches(data: bytes, region: str, filename: str) -> bool:
    if len(data) < 16:
        return False
    md5, _ = _md5(region, filename)
    return (
        data[0] == ((~md5[4]) & 0xFF)
        and data[1] == ((~md5[5]) & 0xFF)
        and data[2] == ((~md5[6]) & 0xFF)
        and data[3] == 12
    )


def detect_v3(data: bytes, filename: str, region: str | None = None) -> HonkyV3Meta:
    candidates = [region] if region else ["jp", "gl"]
    for candidate in candidates:
        if candidate is None or not _header_signature_matches(data, candidate, filename):
            continue
        if data[7] not in (0, 1):
            continue
        _, basename = _md5(candidate, filename)
        computed = sum(_prefix(candidate)) + sum(basename)
        encoded = (int(data[10]) << 8) | int(data[11])
        if encoded != computed:
            continue
        return HonkyV3Meta(
            region=str(candidate).lower(),
            filename=filename,
            name_sum=encoded,
            flipped=(data[7] == 1),
        )
    requested = f" for region {region!r}" if region else ""
    raise ValueError(f"invalid or unsupported Honky v3 header for {filename!r}{requested}")


def _crypt_v3(data: bytes, meta: HonkyV3Meta) -> bytes:
    state = _v3_table(meta.region)[int(meta.name_sum) & 0x3F]
    if meta.flipped:
        state = (~state) & 0xFFFFFFFF
    out = bytearray(len(data))
    # v3 uses the MSVC LCG and the high byte of each state.
    for i, value in enumerate(data):
        out[i] = value ^ ((state >> 24) & 0xFF)
        state = (state * 214013 + 2531011) & 0xFFFFFFFF
    return bytes(out)


def decrypt_v3(data: bytes, filename: str, region: str | None = None) -> tuple[bytes, HonkyV3Meta]:
    meta = detect_v3(data, filename, region)
    return _crypt_v3(data[16:], meta), meta


def _emit_v3_header(meta: HonkyV3Meta) -> bytes:
    md5, basename = _md5(meta.region, meta.filename)
    computed = sum(_prefix(meta.region)) + sum(basename)
    if computed != int(meta.name_sum):
        raise ValueError(
            f"Honky v3 name sum mismatch for {meta.filename!r}: "
            f"metadata={meta.name_sum}, computed={computed}"
        )
    return bytes(
        [
            (~md5[4]) & 0xFF,
            (~md5[5]) & 0xFF,
            (~md5[6]) & 0xFF,
            12,
            0,
            0,
            0,
            1 if meta.flipped else 0,
            (meta.name_sum >> 24) & 0xFF,
            (meta.name_sum >> 16) & 0xFF,
            (meta.name_sum >> 8) & 0xFF,
            meta.name_sum & 0xFF,
            0,
            0,
            0,
            0,
        ]
    )


def encrypt_v3(plaintext: bytes, meta: HonkyV3Meta, filename: str | None = None) -> bytes:
    target_name = filename or meta.filename
    _, basename = _md5(meta.region, target_name)
    target = HonkyV3Meta(
        region=meta.region,
        filename=target_name,
        name_sum=sum(_prefix(meta.region)) + sum(basename),
        flipped=meta.flipped,
    )
    return _emit_v3_header(target) + _crypt_v3(plaintext, target)


def _v4_header_matches(data: bytes, region: str, filename: str) -> bool:
    return (
        _header_signature_matches(data, region, filename)
        and data[7] == 2
        and 0 <= data[6] < len(_V4_LCG_PARAM)
    )


def detect_v4(data: bytes, filename: str, region: str | None = None) -> HonkyV4Meta:
    candidates = [region] if region else list(NAME_PREFIXES)
    for candidate in candidates:
        if candidate is not None and _v4_header_matches(data, candidate, filename):
            return HonkyV4Meta(region=str(candidate).lower(), filename=filename, lcg_index=int(data[6]))
    requested = f" for region {region!r}" if region else ""
    raise ValueError(f"invalid or unsupported Honky v4 header for {filename!r}{requested}")


def _crypt_v4(data: bytes, meta: HonkyV4Meta) -> bytes:
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
    return _crypt_v4(data[16:], meta), meta


def _emit_v4_header(meta: HonkyV4Meta) -> bytes:
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
    return _emit_v4_header(target) + _crypt_v4(plaintext, target)
