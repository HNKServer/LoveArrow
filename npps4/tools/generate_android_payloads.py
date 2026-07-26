"""Regenerate Android first-run workspace and Alembic payload modules.

Run from any working directory. Payloads are deterministic: file order, ZIP
metadata and Base64 wrapping are fixed so PC/Android source trees can be
compared byte-for-byte.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path
import textwrap
import zipfile

PKG = Path(__file__).resolve().parents[1]
PYROOT = PKG.parent
TOOLS = PKG / "tools"
FIXED_DATE = (2026, 7, 25, 0, 0, 0)


def _archive(files: list[tuple[str, Path]]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in files:
            info = zipfile.ZipInfo(name, FIXED_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return output.getvalue()


def _write_module(path: Path, title: str, payload: bytes) -> None:
    encoded = base64.b64encode(payload).decode("ascii")
    chunks = textwrap.wrap(encoded, 100)
    body = "\n".join(f"    {chunk!r}" for chunk in chunks)
    path.write_text(
        f'"""{title}\n\nGenerated deterministically from the current source tree.\n"""\n\nPAYLOAD_B64 = (\n{body}\n)\n',
        encoding="utf-8",
    )


def generate_workspace() -> None:
    names = [
        "external/badwords.py",
        "external/login_bonus.py",
        "external/beatmap.py",
        "external/live_unit_drop.py",
        "external/live_box_drop.py",
        "external/custom_downloader.py",
        "npps4/server_data.json",
        "npps4/server_data_schema.json",
        "default_server_key.pem",
        "npps4_default_server_key.pem",
        "honoka_server_key.pem",
        "config.sample.toml",
        "cn_server_info_99_0_115.zip",
    ]
    files = [(name, PYROOT / name) for name in names]
    missing = [str(path) for _, path in files if not path.is_file()]
    if missing:
        raise FileNotFoundError("workspace payload input missing: " + ", ".join(missing))
    _write_module(
        TOOLS / "android_workspace_payload.py",
        "Embedded first-run workspace defaults for Chaquopy/Android.",
        _archive(files),
    )


def generate_alembic() -> None:
    alembic = PKG / "alembic"
    files: list[tuple[str, Path]] = [
        (name, alembic / name) for name in ("README", "env.py", "script.py.mako")
    ]
    files.extend(
        (f"versions/{path.name}", path)
        for path in sorted((alembic / "versions").glob("*.py"))
    )
    _write_module(
        TOOLS / "android_alembic_payload.py",
        "Embedded Alembic tree for Android workspace compatibility.",
        _archive(files),
    )


def main() -> None:
    generate_workspace()
    generate_alembic()
    print("Regenerated Android workspace and Alembic payloads.")


if __name__ == "__main__":
    main()
