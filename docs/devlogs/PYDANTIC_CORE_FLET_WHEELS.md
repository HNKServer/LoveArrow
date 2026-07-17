# NPPS4 Android: Pydantic v2 / `pydantic-core` wheel profile

This source package is configured for the native Pydantic v2 path on Android.
It does not downgrade NPPS4 to Pydantic v1 and does not use a local shim.

## Target

```text
Chaquopy Python: 3.13
Android API wheel tag: android_24
Android ABIs: arm64-v8a, x86_64
Pydantic: 2.11.10
pydantic-core: 2.33.2
```

The important part is the exact pair:

```text
pydantic==2.11.10
pydantic-core==2.33.2
```

`pydantic-core` is not a pure Python dependency. It is a native extension, so
Chaquopy must receive an Android wheel for every ABI you build.

## What was changed

`app/build.gradle` now searches for wheels in this order:

```text
1. app/src/main/python/wheels
2. https://pypi.flet.dev
3. normal PyPI, for pure-Python packages and non-Android packages
```

The Android dependency files are pinned so pip cannot accidentally pair Pydantic
with an incompatible `pydantic-core` version:

```text
app/src/main/python/requirements-android.txt
app/src/main/python/constraints-android.txt
```

## Pre-fill the local wheelhouse

From the project root:

```bash
bash tools/pydantic_core_android/fetch_flet_pydantic_core_wheels.sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File tools\pydantic_core_android\fetch_flet_pydantic_core_wheels.ps1
```

The scripts download these two files into `app/src/main/python/wheels`:

```text
pydantic_core-2.33.2-cp313-cp313-android_24_arm64_v8a.whl
pydantic_core-2.33.2-cp313-cp313-android_24_x86_64.whl
```

If the wheel directory is empty, Gradle/Chaquopy can still try to resolve the
same files from `https://pypi.flet.dev` because `app/build.gradle` includes it as
an extra index URL.

## Build after fetching wheels

After the wheel files are present, build the app as before:

```bash
bash scripts/build_apk_pydantic2.sh
```

or on Windows:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_apk_pydantic2.ps1
```

## Do not blindly bump versions

`pydantic-core` versions are tightly bound to Pydantic releases. For example,
newer `pydantic-core` wheels may exist while still being incompatible with the
Pydantic version selected by pip. Keep the pair pinned unless you confirm that
Flet has matching Android wheels for the exact `pydantic-core` version required
by the Pydantic release you choose.

## Offline build

For an offline Android build, run one of the fetch scripts while online and keep
both `.whl` files under `app/src/main/python/wheels`. Chaquopy searches that
local directory before the remote index.
