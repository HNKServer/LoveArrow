# NPPS4 v5.18 Final Validation

Build: `v5.18-cn-shop-localization-lp-items`

## Scope

The release was rebuilt from the v5.17 source baseline. The functional changes are limited to:

1. CN sticker-shop localization;
2. CN recovery-item Master generation;
3. active-profile filtering of shared recovery-item inventory;
4. `LOVEARROWSHOOT` recovery-item top-up;
5. version, schema, documentation and validators.

No friend/costume/live/accessory/secret-box implementation file was changed except the serial-code resource grant and historical validator marker.

## Sticker shop

- Total configured rows: **849**.
- Rows with `name_cn`: **804**.
- Unique `(add_type, item_id)` CN name entries: **799**.
- Rows whose localized name contains Chinese text: **788**.
- Remaining Latin-only names: **16**, all stylized/proper event names such as `PERFECT WORLD`, `WHITE ISLAND`, and named LoveLive events.
- Exact supplied CN client catalogue projects **796** safe rows.
- Every one of those 796 CN-visible rows has a non-empty localized title.
- Item 5 is named **辅助招募券**.
- Old preserved `server_data.json` files are supported by a compact 38 KiB bundled name map and an active-Master batch fallback.
- Both fallback results use `BasicSchoolIdolContext.cache` and are released at request completion.

## Recovery items

- `cn_recovery_items.json`: **52** rows.
- ID set matches honoka/client list exactly:
  - `1–27`;
  - `801–805`, `995`;
  - `777001–777003`;
  - `777005–777020`.
- All rows use supported recovery semantics (`recovery_type` 1 or 2).
- The generated CN `item.db_` was created in a temporary directory and inspected directly:
  - `recovery_item_m`: **52** rows;
  - ID 1: `方糖[耐力50]`, type 2, value 50;
  - manifest: `52:bundled_cn_recovery_items`.
- Generator cache marker: `cn_honoka_master:v7_recovery_items`.
- Shared player recovery inventory is filtered against the active profile's `recovery_item_m` before serialization.
- `LOVEARROWSHOOT` tops every recovery item supported by the current active Master to **9999**.
- Item 1 and Item 5 remain explicitly included in the ordinary-item top-up set.

## Preserved v5.17 contracts

The inherited v5.17 validator confirms:

- friend costumes remain bound to the exact projected owned card;
- main singer and navigation partner appearances remain separate;
- dedicated accessory creation still requires two identical mapped cards;
- the test code still keeps three eligible dedicated-accessory copies;
- festival pages `5K`, `5L`, `5M`, `5N` remain configured for CN and GL;
- Small Happiness remains GL-only;
- the `secretbox.py` startup import fix remains present.

## Automated checks

Performed independently on both PC and Android source trees:

- `validate_v517.py`: passed;
- `validate_v518.py`: passed;
- complete Python-tree `compileall`: passed;
- generated CN item database inspection: passed;
- JSON Schema Draft 2020-12 validation of `server_data.json`: passed with 0 errors;
- actual Pydantic `SerializedServerData.model_validate_json`: parsed 849 shop rows and 14 secret-box pages;
- Android Kotlin search fix present: `searchInput.text.isNotBlank()`;
- forbidden old Kotlin expression absent: `this.text.isNotBlank()`;
- PC and Android embedded `npps4` trees: **242 files**, identical paths and **0 byte differences**.

Only 13 source/artifact paths differ from the v5.17 PC baseline, all belonging to this release's stated scope.

## Packaging boundary

The source ZIPs are checked separately with `zip -T` after creation. No Gradle build or APK build was performed, so this report does not claim APK compilation or device execution.
