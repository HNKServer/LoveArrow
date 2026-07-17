# v4.37 NPPS4-first CN compatibility cleanup

This release corrects the over-broad honoka-style substitutions introduced in v4.35/v4.36 while retaining the useful CN compatibility and diagnostics.

## Restored NPPS4 behavior

- `announce/checkState`: restored present-box counting (`present_cnt`) and NPPS4 reward integration.
- `challenge/challengeInfo`: restored NPPS4's original response model instead of forcing honoka's empty list.
- `livese/liveseInfo`: restored all NPPS4 live-SE IDs `[1, 2, 3, 4, 99]`.
- `login/topInfo` and `login/topInfoOnce`: restored NPPS4 badge counts and notification flags.
- `payment/productList`: restored `show_point_shop=True`.
- `banner/bannerList`: removed the hard-coded honoka secret-box banner replacement.

## Additive / capability-gated CN compatibility retained

- CN 9.7.x omits only unsupported banner type 18; all other clients keep NPPS4's SIF2 transfer banner. NPPS4's WebView/TenFes banner remains available.
- `item/list` keeps NPPS4's `reinforce_item_list` and `reinforce_info`, while adding the CN metadata fields to general/buff items.
- `multiunit/multiunitscenarioStatus` keeps the original NPPS4 list and adds `unlocked_multi_unit_scenario_ids`.
- v4.34's starter-unit idempotency and announcement/API-doc route separation remain.
- CN batch diagnostics remain and a build marker is printed at startup so stale APK/source builds can be identified immediately.

No masterdata, archive download, WebUI translation, database migration, or friend-system behavior was replaced in this release.
