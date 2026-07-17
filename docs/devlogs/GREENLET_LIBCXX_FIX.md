# greenlet / libc++_shared.so Android runtime fix

The previous Pydantic v2 build can now install `pydantic-core`, but server start
may fail later when SQLAlchemy asyncio imports `greenlet`:

```text
dlopen failed: library "libc++_shared.so" not found: needed by .../greenlet/_greenlet.cpython-313-aarch64-linux-android.so
```

This is not a Python-level import problem. The Android `greenlet` wheel is native
code and is linked against the NDK shared C++ runtime, `libc++_shared.so`. Because
this wrapper does not compile any C++ code of its own, Android Gradle Plugin has
nothing that would automatically pull that shared runtime into the APK.

This package fixes it in two ways:

1. `app/build.gradle` now has a `copyNdkLibcxxShared` task. Before `preBuild`, it
   copies the correct `libc++_shared.so` files from the installed Android NDK to:

   ```text
   app/src/main/jniLibs/arm64-v8a/libc++_shared.so
   app/src/main/jniLibs/x86_64/libc++_shared.so
   ```

2. `Npps4Application.onCreate` preloads `System.loadLibrary("c++_shared")` before
   the Chaquopy Python runtime imports SQLAlchemy/greenlet.

## What you need locally

Install Android SDK NDK in Android Studio, or point Gradle at an existing NDK:

```properties
# local.properties
ndk.dir=C\:\\Users\\<you>\\AppData\\Local\\Android\\Sdk\\ndk\\<version>
```

or set one of these environment variables:

```text
ANDROID_NDK_HOME
ANDROID_NDK_ROOT
NDK_HOME
```

Then build normally:

```bash
bash tools/pydantic_core_android/fetch_flet_pydantic_core_wheels.sh
bash scripts/build_apk_pydantic2.sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File tools\pydantic_core_android\fetch_flet_pydantic_core_wheels.ps1
powershell -ExecutionPolicy Bypass -File scripts\build_apk_pydantic2.ps1
```

If the build fails with `Android NDK not found`, install NDK via Android Studio's
SDK Manager. You do not need an emulator or nested virtualization for this.
