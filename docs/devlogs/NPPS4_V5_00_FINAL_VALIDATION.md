# NPPS4 v5.00 final validation

- Passed: 73
- Failed: 0

PASS: Android Python compileall
PASS: PC Python compileall
PASS: config.sample.toml TOML parse
PASS: config.sample.toml disables legacy global backend
PASS: config.sample.toml contains profile-specific download tree
PASS: config.dual.sample.toml TOML parse
PASS: config.dual.sample.toml disables legacy global backend
PASS: config.dual.sample.toml contains profile-specific download tree
PASS: config.cn-local.sample.toml TOML parse
PASS: config.cn-local.sample.toml disables legacy global backend
PASS: config.cn-local.sample.toml contains profile-specific download tree
PASS: config.gl-online.sample.toml TOML parse
PASS: config.gl-online.sample.toml disables legacy global backend
PASS: config.gl-online.sample.toml contains profile-specific download tree
PASS: dual sample enables CN and GL together
PASS: dual sample CN local backend
PASS: dual sample GL online backend
PASS: old global quick-switch UI/runtime removed
PASS: Wrapper explicit selector token: MODE_DISABLED
PASS: Wrapper explicit selector token: MODE_LOCAL
PASS: Wrapper explicit selector token: MODE_ONLINE
PASS: Wrapper explicit selector token: setProfileMode
PASS: Wrapper explicit selector token: PROFILE_CN
PASS: Wrapper explicit selector token: PROFILE_GL
PASS: Wrapper exposes independent explicit CN/GL selectors
PASS: old download_profile preference migrates once then is removed
PASS: old two-mode values have deterministic migration
PASS: Wrapper prevents both profiles being disabled
PASS: obsolete diagnostic-report GUI and bridge removed
PASS: Wrapper no longer defaults to port 51376
PASS: Wrapper defaults to port 8080
PASS: generated Android config keeps optional stubs disabled
PASS: Kotlin sources have no parser/structure errors
PASS: runtime code has no removed process-global download/region reads
PASS: CN wrappers are registered from raw capability config, not import-time ContextVar
PASS: legacy User.key claim is restricted to historical default profile
PASS: capability/version helpers accept explicit profile
PASS: Android payload includes dual-profile migration
PASS: Android payload includes profile-story migration
PASS: GL event_common count is 755
PASS: GL multi_unit_scenario count is 57
PASS: clean dual-profile runtime imports and registers required routes
PASS: CN/GL versions remain independent in one process
PASS: Desktop Alembic contains v5 profile tables
PASS: Desktop Alembic stamped at profile_story_state
PASS: Desktop Alembic preserves two identities on one shared user
PASS: Desktop Alembic story state includes profile column
PASS: Android schema contains v5 profile tables
PASS: Android schema stamped at profile_story_state
PASS: Android schema preserves two identities on one shared user
PASS: Android schema story state includes profile column
PASS: GL accessory lifecycle produced enhanced/rank-up persistent accessory
PASS: GL accessory lifecycle persisted Glass/Jewel material consumption
PASS: GL accessory lifecycle persisted final unload state
PASS: area/list safe endpoint registered
PASS: payment/month safe endpoint registered
PASS: unknown batch endpoint uses HTTP-200 game error
PASS: unknown direct SIF endpoint uses signed game error path
PASS: v4.60 verified banner resource preserved: npps4_data_transfer.png
PASS: v4.60 verified banner resource preserved: wv_ba_117.png.imag
PASS: v4.60 verified banner resource preserved: tx_wv_ba_117.texb
PASS: v4.60 verified banner resource preserved: 4_0_999.zip
PASS: Android/PC Python tree parity (2314 files)
PASS: CN/dual-profile contract guard
PASS: GL APK SHA-256 matches build report
PASS: GL APK package renamed for side-by-side install
PASS: GL encrypted server_info points to 127.0.0.1:8080
PASS: GL settings Activity default points to 127.0.0.1:8080
PASS: GL APK v2 signature independently verifies
PASS: GL APK v1 signature verifies
PASS: GL APK stored entries are 4-byte aligned
PASS: Android Wrapper version is 0.5.0 / 500
PASS: final Build ID set

## Explicitly not validated here

- Android Wrapper Gradle/Android SDK build was not possible in this environment.
- CN↔GL friendship and GL accessory UI still require two real clients.
- The GL test APK passed structural/signature checks but has not been installed on a physical device here.
