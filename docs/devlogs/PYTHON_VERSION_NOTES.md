# Python / Chaquopy version notes

This variant targets Chaquopy Python 3.13, not 3.14.

Why: Chaquopy 17 supports Python 3.14 itself, but its Android wheel repository currently has `pycryptodomex` wheels up to cp313, not cp314. NPPS4 requires Python 3.12+, so Python 3.13 satisfies NPPS4 while keeping `pycryptodomex` installable on Android.

Install CPython 3.13 on the build machine, then keep `app/build.gradle` as:

```gradle
chaquopy {
    defaultConfig {
        version = "3.13"
        buildPython("py", "-3.13")
    }
}
```

If the Windows Python launcher cannot find 3.13, replace `buildPython("py", "-3.13")` with the full path to Python 3.13, for example:

```gradle
buildPython("C:/Users/YOU/AppData/Local/Programs/Python/Python313/python.exe")
```
