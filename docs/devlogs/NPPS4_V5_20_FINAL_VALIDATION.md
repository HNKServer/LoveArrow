# NPPS4 v5.20 Final Validation

Build: `v5.20-role-profile-master-contract-fix`

## Corrected scope

- The missing signed Thank-You Festival pages observed on-device are Aqours and Liella!, not Nijigasaki.
- Nijigasaki remains configured and is explicitly covered by the regression checks.
- The implementation starts from the supplied v5.19 source; no unverified prior v5.20 package is treated as a baseline.

## Role projection

- Friend list/search uses the navigation partner.
- Profile `center_unit_info` uses the active main-deck lead.
- Profile `navi_unit_info` uses the navigation partner.
- Live guest support uses the main-deck lead.
- Lead and navigator exclude each other's owning IDs during fallback.
- Cross-profile fallback prefers a safe card of the same character before a generic safe card.
- Costume data remains bound to the exact projected owned card.

## Signed Thank-You Festival pools

- `5K / 1718`: μ's.
- `5L / 1719`: Aqours.
- `5M / 1720`: Nijigasaki.
- `5N / 1721`: Liella!.
- Pool generation uses the exact per-profile Unit-to-category catalogue, then intersects with active runtime Unit rows.
- CN and GL both retain non-empty SSR and UR pools for all four categories.
- Dedicated checks confirm that Aqours and Liella! survive the active-Unit intersection and that Nijigasaki remains visible.

## Exact client contracts

| Contract | CN | GL |
|---|---:|---:|
| Recognized Unit IDs | 3644 | 3998 |
| Recognized accessory IDs | 336 | 562 |
| Dedicated-accessory mappings | 258 | 484 |
| LP-recovery item IDs | 52 | 47 |

- Every dedicated accessory and target Unit exists in the corresponding exact client catalogue.
- CN-only LP items 801–805 are not projected into GL.
- `LOVEARROWSHOOT` verifies committed LP-item inventory and preserves two material copies plus one wearable copy for exact dedicated-accessory targets.

## Android clean-install payload

- Embedded `server_data.json` is byte-for-byte equal to the normal source copy.
- Embedded `server_data_schema.json` is byte-for-byte equal to the normal source copy.
- The clean-install payload contains all 804 `name_cn` fields.
- The clean-install payload contains all four signed festival pages.

## Executed validation

- `python -m npps4.tools.validate_v520`: passed.
- Inherited `python -m npps4.tools.validate_v517`: passed.
- `tools/validate_v516_startup_imports.py`: passed.
- Critical modified modules: AST parse, bytecode compilation and import smoke passed.
- Profile catalogue and role-fallback runtime smoke: passed.
- Generated CN Master contract check: 3963 Unit rows, 336 accessories, 258 dedicated mappings and 52 recovery items.
- Full Python `compileall`: passed for both PC and Android trees using a disposable bytecode cache.
- `server_data.json` against `server_data_schema.json`: zero errors for both trees.
- PC and Android embedded Python trees: 2331 files, byte-for-byte identical.
- Kotlin search fix `searchInput.text.isNotBlank()`: present in the Android tree.
- ZIP CRC/integrity and SHA-256: verified after packaging and reported with the delivered archives.

## Environment limitation

No Gradle APK build or physical CN/GL client test is performed in this container. The package is source-level and simulated-contract validated; final UI behavior still requires the same on-device scenarios that exposed the original regressions.
