# NPPS4 v5.10 最终验证报告

- 通过：**48**
- 失败：**0**

## 检查结果

- PASS — Wrapper default host remains localhost
- PASS — Wrapper default port restored to 51376
- PASS — Endpoint is stored in SharedPreferences
- PASS — Endpoint is restored on app launch
- PASS — Endpoint edits persist while stopped
- PASS — Host and port controls lock while server is active
- PASS — Status indicator uses actual Python host and port
- PASS — Starting and restarting save and lock endpoint
- PASS — Every file editor/log viewer gets search controls
- PASS — Search selects and scrolls to matching line
- PASS — Search supports case-insensitive previous/next navigation
- PASS — Automatic search keeps keyboard focus in the search field
- PASS — Stopped status polling does not overwrite endpoint drafts
- PASS — Android Python compileall
- PASS — PC Python compileall
- PASS — Android and PC Python trees are byte-identical：Android=2319, PC=2319
- PASS — server_data contains exactly one LOVEARROWSHOOT code
- PASS — LOVEARROWSHOOT calls the comprehensive resource function
- PASS — serial-code function is registered
- PASS — Build ID is v5.10
- PASS — Android versionCode/versionName are 510/0.5.10
- PASS — Android Python bridge defaults use 51376
- PASS — Android bundled workspace migrates required serial code
- PASS — Android Python AST parse
- PASS — PC Python AST parse
- PASS — LOVEARROWSHOOT sets game coin target
- PASS — LOVEARROWSHOOT sets friend points target
- PASS — LOVEARROWSHOOT sets free and paid Loveca targets
- PASS — LOVEARROWSHOOT expands card, waiting room and friend capacity
- PASS — LOVEARROWSHOOT restores training energy and LP
- PASS — LOVEARROWSHOOT tops up ordinary items and skips currency item IDs
- PASS — LOVEARROWSHOOT tops up recovery items
- PASS — LOVEARROWSHOOT tops up sticker/exchange currencies
- PASS — LOVEARROWSHOOT tops up SIS
- PASS — LOVEARROWSHOOT tops up supporter members
- PASS — LOVEARROWSHOOT is reusable and idempotent
- PASS — LOVEARROWSHOOT returns a readable result
- PASS — Android workspace migration preserves user server_data fields
- PASS — Android workspace migration preserves custom serial codes
- PASS — Android workspace migration appends LOVEARROWSHOOT
- PASS — Android workspace migration does not duplicate built-in code
- PASS — Android CN contract guard：CN contract guard OK
- PASS — PC CN contract guard：CN contract guard OK
- PASS — Android accessory regression guard：PASS: v5.08 accessory tab and GL auto-create contract guard
- PASS — PC accessory regression guard：PASS: v5.08 accessory tab and GL auto-create contract guard
- PASS — Kotlin parser reports no syntax-level diagnostics：Android SDK classes are unresolved in this environment, so this is parser-only, not a full Android build.
- PASS — Android Wrapper README documents 51376 endpoint
- PASS — Android runtime endpoint code has no stale 8080 default

## 验证边界

- No Android SDK/Gradle wrapper is available in this environment, so the Kotlin/Android project was not fully compiled into an APK.
- SharedPreferences persistence, endpoint locking and editor search were validated by source contract and Kotlin parser checks; final touch/IME behavior still requires device testing.
- LOVEARROWSHOOT was executed through an isolated behavioral harness and not against a real client database in this environment.
