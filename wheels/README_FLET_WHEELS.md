# Local Android wheels

This directory is searched first by Chaquopy's pip configuration.

For the current wrapper configuration, the expected optional local wheel files are:

```text
pydantic_core-2.33.2-cp313-cp313-android_24_arm64_v8a.whl
pydantic_core-2.33.2-cp313-cp313-android_24_x86_64.whl
```

Run this from the project root to pre-fill the directory:

```bash
bash tools/pydantic_core_android/fetch_flet_pydantic_core_wheels.sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File tools\pydantic_core_android\fetch_flet_pydantic_core_wheels.ps1
```

If this directory is left empty, `app/build.gradle` can still ask Chaquopy/pip to
resolve the same wheels from `https://pypi.flet.dev` at build time.
