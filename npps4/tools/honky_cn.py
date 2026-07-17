"""Minimal CN HonokaMiku/HonkyPy-compatible encrypt/decrypt helper.

This is intentionally tiny and self-contained so the Android/Chaquopy build does
not need libhonoka native binaries.  It implements the CN v3/v4 stream cipher
needed for CN SIF1 server_info.json update packages.

Algorithm and constants are compatible with DarkEnergyProcessor/honky-py
(MIT): NAME_PREFIX_CN and KEY_TABLES_CN, plus v3/v4 header handling.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

NAME_PREFIX_CN = b"iLbs0LpvJrXm3zjdhAr4"
KEY_TABLES_CN = [
    0x1B695658, 0x0A43A213, 0x0EAD0863, 0x1400056D, 0xD470461D, 0xB6152300, 0xFBE054BC, 0x9AC9F112,
    0x23D3CAB6, 0xCD8FE028, 0x6905BD74, 0x01A3A612, 0x6E96A579, 0x333D7AD1, 0xB6688BFF, 0x29160495,
    0xD7743BCF, 0x8EDE97BB, 0xCACB7E8D, 0x24D81C23, 0xDBFC6947, 0xB07521C8, 0xF506E2AE, 0x3F48DF2F,
    0x52BEB172, 0x695935E8, 0x13E2A0A9, 0xE2EDF409, 0x96CBA5C1, 0xDBB1E890, 0x4C2AF968, 0x17FD17C6,
    0x1B9AF5A8, 0x97C0BC25, 0x8413C879, 0xD9B13FE1, 0x4066A948, 0x9662023A, 0x74A4FEEE, 0x1F24B4F6,
    0x637688C8, 0x7A7CCF70, 0x91042EEC, 0x57EDD02C, 0x666DA2DD, 0x92839DE9, 0x43BAA9ED, 0x024A8E2C,
    0xD4EE7B72, 0x34C18B72, 0x13B275C4, 0xED506A6E, 0xBC1C29B9, 0xFA66A220, 0xC2364DE3, 0x767E52B2,
    0xE2D32439, 0xE6F0CEF5, 0xD18C8687, 0x14BBA295, 0xCD84D15B, 0xA0290F82, 0xD3E95AFC, 0x9C6A97B4,
]
_V4_LCG_PARAM = [
    (1103515245, 12345, 15),
    (22695477, 1, 23),
    (214013, 2531011, 24),
    (65793, 4282663, 8),
]


@dataclass(frozen=True)
class CnHonkyMeta:
    version: int
    filename: str
    flip_v3: bool = False
    v4_lcg_index: int = 0


def _calculate_md5(filename: str | bytes) -> tuple[bytes, bytes]:
    if isinstance(filename, str):
        filename_b = filename.encode("utf-8")
    else:
        filename_b = filename
    basename = os.path.basename(filename_b)
    md5 = hashlib.md5(NAME_PREFIX_CN, usedforsecurity=False)
    md5.update(basename)
    return md5.digest(), basename


def _initial_state(meta: CnHonkyMeta) -> tuple[int, int, int, int]:
    md5, basename = _calculate_md5(meta.filename)
    if meta.version == 3:
        name_sum = sum(NAME_PREFIX_CN) + sum(basename)
        key = KEY_TABLES_CN[name_sum & 0x3F]
        if meta.flip_v3:
            key = (~key) & 0xFFFFFFFF
        a, c, shift = _V4_LCG_PARAM[2]  # MSVC LCG used by v3
        return key, a, c, shift
    if meta.version == 4:
        idx = int(meta.v4_lcg_index)
        if idx < 0 or idx >= len(_V4_LCG_PARAM):
            raise ValueError(f"invalid CN v4 LCG index: {idx}")
        a, c, shift = _V4_LCG_PARAM[idx]
        key = (md5[8] << 24) | (md5[9] << 16) | (md5[10] << 8) | md5[11]
        return key, a, c, shift
    raise ValueError(f"unsupported CN honky version: {meta.version}")


def _crypt_block(data: bytes, meta: CnHonkyMeta) -> bytes:
    update_key, a, c, shift = _initial_state(meta)
    out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = b ^ ((update_key >> (shift & 0x1F)) & 0xFF)
        update_key = (update_key * a + c) & 0xFFFFFFFF
    return bytes(out)


def _emit_header(meta: CnHonkyMeta) -> bytes:
    md5, basename = _calculate_md5(meta.filename)
    if meta.version == 3:
        name_sum = sum(NAME_PREFIX_CN) + sum(basename)
        return bytes([
            (~md5[4]) & 0xFF,
            (~md5[5]) & 0xFF,
            (~md5[6]) & 0xFF,
            12,
            0,
            0,
            0,
            1 if meta.flip_v3 else 0,
            (name_sum >> 24) & 0xFF,
            (name_sum >> 16) & 0xFF,
            (name_sum >> 8) & 0xFF,
            name_sum & 0xFF,
            0,
            0,
            0,
            0,
        ])
    if meta.version == 4:
        return bytes([
            (~md5[4]) & 0xFF,
            (~md5[5]) & 0xFF,
            (~md5[6]) & 0xFF,
            12,
            0,
            0,
            meta.v4_lcg_index & 0xFF,
            2,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ])
    raise ValueError(f"unsupported CN honky version: {meta.version}")


def _detect_meta(encrypted: bytes, filename: str) -> CnHonkyMeta:
    if len(encrypted) < 16:
        raise ValueError("insufficient CN honky header")
    header = encrypted[:16]
    md5, _ = _calculate_md5(filename)
    if header[0] != ((~md5[4]) & 0xFF) or header[1] != ((~md5[5]) & 0xFF) or header[2] != ((~md5[6]) & 0xFF):
        raise ValueError(f"invalid CN honky header for {filename}")
    if header[7] < 2:
        return CnHonkyMeta(version=3, filename=filename, flip_v3=bool(header[7]))
    if header[7] == 2:
        return CnHonkyMeta(version=4, filename=filename, v4_lcg_index=int(header[6]))
    raise ValueError(f"unsupported CN honky header version marker: {header[7]}")


def decrypt_server_info(encrypted: bytes, filename: str = "server_info.json") -> tuple[bytes, CnHonkyMeta]:
    meta = _detect_meta(encrypted, filename)
    return _crypt_block(encrypted[16:], meta), meta


def encrypt_server_info(plaintext: bytes, meta: CnHonkyMeta | None = None, filename: str = "server_info.json") -> bytes:
    if meta is None:
        meta = CnHonkyMeta(version=3, filename=filename)
    else:
        meta = CnHonkyMeta(version=meta.version, filename=filename, flip_v3=meta.flip_v3, v4_lcg_index=meta.v4_lcg_index)
    return _emit_header(meta) + _crypt_block(plaintext, meta)
