# -*- mode: python ; coding: utf-8 -*-

# Keep runtime package data inside the PyInstaller bundle.  v5.32 reads these
# files through importlib.resources, so a build without them can start but will
# fail in the CN/GL Master, accessory, scouting and WebUI paths.

a = Analysis(
    ["pyinstaller_bootstrap.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("alembic.ini", "."),
        ("npps4/alembic", "npps4/alembic"),
        ("npps4/assets", "npps4/assets"),
        ("npps4/webui/static", "npps4/webui/static"),
        ("npps4/server_data_schema.json", "npps4"),
    ],
    hiddenimports=[
        "aiosqlite",
        "psycopg",
        "winloop._noop",
        "npps4.scriptutils.boot",
        "npps4.scriptutils.user",
        "npps4.script_dummy",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="npps4",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="npps4",
)
