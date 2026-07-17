# v4.21 CN one-pass download/version-header fix

This revision fixes the remaining mismatch between honoka-chan CN 9.7.x and NPPS4's historical two-part version handling.

## Why

The CN client expects the download package/server version to be exposed as the exact string `97.4.6`.  v4.20 fixed the `download/update` payload version, but normal response headers still used NPPS4's old `util.sif_version_string(config.get_latest_version())`, which truncates the value to `97.4`.  That can make the client keep believing the 99_* update package stage is not complete and never advance cleanly to the bulk resource stage.

The CN client also sends the Android application version such as `9.7.1` in the `Client-Version` header.  NPPS4's legacy version check compares that header against the server/download package version, which is not how honoka-chan works.  In CN mode the generic check is now bypassed; download/update and Server-Version headers are the source of truth for package updates.

## Changes

- Add `config.get_latest_version_string()` and keep `97.4.6` intact for `cn_archive`.
- Use the raw version string for `Server-Version` in normal NPPS4 responses and GHome responses.
- Add `config.skip_generic_client_version_check()` and bypass NPPS4's legacy Client-Version tuple comparison in CN mode.
- Keep non-CN/GL behavior unchanged.
