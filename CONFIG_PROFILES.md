# NPPS4 CN/GL profile notes

This modified NPPS4 tree contains compatibility code for both:

- CN / honoka-chan-style patched clients
- GL / community NPPS4-style patched clients

## CN local archive profile

Use this when testing the CN 9.7.x client with local flat CDN archives.

```toml
[download]
backend = "cn_archive"
send_patched_server_info = true

[download.cn_archive]
android_archives = "list_CN_Android"
db_root = "data/db_cn_honoka"
application_version = "9.7.1"
client_version = "97.4.6"
update_package_type = 99
server_info_override = "99_0_115.zip"

[compat]
region = "cn"
cn_autocreate_ghome_users = true
cn_wrappers = true
cn_optional_stubs = true
```

## GL online DLAPI/CDN profile

Use this when the client APK points to your local NPPS4 server but you want game packages to come from an online NPPS4-DLAPI endpoint.

```toml
[download]
backend = "n4dlapi"
send_patched_server_info = true

[download.n4dlapi]
server = "https://ll.sif.moe/npps4_dlapi/"
shared_key = ""

[compat]
region = "global"
cn_autocreate_ghome_users = false
cn_wrappers = false
cn_optional_stubs = false
```

## Current limitation

The current download backend and master DB are still selected globally when the server process imports `npps4.download`. Dual RSA keys allow both key families to authenticate, but true simultaneous CN/GL play with automatic per-session master-data and download switching is not complete yet.
