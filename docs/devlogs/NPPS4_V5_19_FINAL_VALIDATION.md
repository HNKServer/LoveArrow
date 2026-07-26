# NPPS4 v5.19 Final Validation

Build: `v5.19-clean-config-localization-lp-items`

## Configuration cleanup

- Removed `npps4/assets/cn_sticker_shop_names.json`.
- Removed the request-time compact-name catalogue loader.
- Removed the request-time Item/Background/Award/Museum/Accessory Master title synthesis.
- `server_data.json` is now the sole source for configured CN sticker-shop display names.
- No player database schema or migration was changed.

## Preserved v5.18 behavior

- 849 sticker-shop configuration rows parse successfully.
- Exact CN client capability projection still exposes 796 safe rows.
- Every CN-visible safe row has a non-empty `name_cn` directly in `server_data.json`.
- 52 CN LP-recovery items remain bundled; active GL support remains filtered by the GL catalogue.
- `LOVEARROWSHOOT` still tops supported LP items and scouting-ticket items, including Item 5, to 9999.
- All four signed Thank-You Festival pages remain configured.
- v5.17 social-costume separation, dedicated-accessory rules, and the `secretbox.py` startup import fix remain present.

## Executed checks

- `validate_v517.py`: passed for PC and Android trees.
- `validate_v518.py`: passed for PC and Android trees in v5.19 inheritance mode.
- `validate_v519.py`: passed for PC and Android trees.
- Full Python `compileall`: passed for both trees using a disposable bytecode cache.
- `server_data.json` against `server_data_schema.json`: zero errors for both trees.
- PC and Android embedded Python trees: 2328 files, byte-for-byte identical.
- Obsolete fallback symbols and asset references: absent.
- ZIP integrity: checked after packaging.

## Environment limitation

A full host-side import of the server application was not available because the validation container does not include the runtime `Cryptodome` dependency. The modified modules were AST-parsed and compiled, and the dedicated startup-import regression check for `secretbox.py` passed. No Gradle/APK build was performed.
