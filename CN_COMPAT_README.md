# NPPS4 CN compatibility branch — minimal-adapter strategy

This branch deliberately keeps NPPS4 as the gameplay server.  honoka-chan is
used only as a compatibility reference for CN client bootstrapping, GHome/Shengqu
account glue, raw CN archives, and the `99_0_115.zip` server-info override.

The guiding rule is:

> Do not replace NPPS4 gameplay with honoka behavior unless a CN client capture
> proves NPPS4's existing implementation cannot satisfy that endpoint.

## Necessary compatibility additions

These are the parts that are genuinely required for an unmodified CN client or a
CN archive mirror:

- tolerant `LANG` parsing plus `Language.zh_cn` / `Language.zh_tw`, so CN header
  variants do not get rejected by FastAPI before the request reaches NPPS4;
- a Shengqu/GHome bridge for `/v1/basic/*`, `/v1/account/*`, `/v1/guest/status`,
  agreement/report endpoints, because the CN client talks to that SDK layer
  before entering `/main.php`;
- GHome-to-NPPS4 account mapping that preserves NPPS4's original `/login/login`:
  the bridge creates/updates a normal NPPS4 user with `key = str(user_id)` and
  `password = ticket`, matching honoka's observed `userid + ticket` game-login
  handoff without weakening NPPS4's password check;
- `download.backend = "cn_archive"`, which serves raw CN folders such as
  `list_CN_Android/1_578_1.zip` directly;
- the CN download quirk from honoka-chan: `/download/batch` maps
  `package_type = 0` to `package_type = 4`;
- the `99_0_115.zip` override hook, because the CN packages contain an encrypted
  `config/server_info.json` and the client must receive the private-server
  version last.

## Compatibility tiers

In this branch, `optional` does **not** mean "unimportant to the CN experience".
It means "temporary fake compatibility that returns empty/no-op data and can
mask missing real systems".  Real features should be implemented whenever they
can be connected to NPPS4's own state model without breaking existing behavior.

The tiers are:

- `cn_wrappers`: safe CN action aliases that call NPPS4 real systems. Enabled by default.
- `extend_npps4_system`: real new persistence/logic added to NPPS4, shared by CN and global clients when appropriate. Enabled once implemented.
- `cn_optional_stubs`: temporary empty/no-op responses for log discovery only. Disabled by default.

These items are honoka-inspired, but not enabled by default because they can mask
missing real features:

- extra honoka-style headers on `/main.php` responses.  NPPS4 already sends the
  normal SIF headers.  Enable `[compat].cn_main_headers = true` only if logs show
  the CN client needs the extra fields;
- fallback stubs should only be used for temporary log discovery.  Friend request/approval,
  greeting, accessory, live continue, random-live continue, and reward sell-unit
  endpoints are no longer stubs; they are real NPPS4 state-backed paths.  Keep
  `[compat].cn_optional_stubs = false` for correctness testing.


## Friend interoperability

v7 adds real shared friend persistence instead of treating CN friend actions as
fallback stubs.  `friend/request`, `friend/response`, `friend/expel`,
`friend/requestCancel`, and `friend/list` now use a single `friend_link` table in
NPPS4's main database.  Because GHome accounts are mapped onto ordinary NPPS4
`User` rows, CN-client users and global/community-client users can become
friends with each other as long as they connect to the same server/database and
use the same master-data universe.

The relation states are stored once per direction so both client families can
see the same workflow:

- requester -> target: `PENDING`;
- target -> requester: `APPROVAL_WAIT`;
- accepted friends: both directions become `FRIEND`;
- cancel/reject/expel removes both directions.

This is an `extend_npps4_system` change, not a honoka shortcut: friend search and
friend list still render users through NPPS4's user/unit/center-card model.

## Things intentionally not ported from honoka-chan

- all-card/all-song/all-scenario unlocking as the normal account baseline;
- honoka's simplified live, event, gacha, reward, rank, unit-growth behavior;
- honoka's default high-resource user profile;
- global replacement of NPPS4 endpoints with Go behavior;
- automatic runtime decryption/re-encryption of `server_info.json` inside
  `99_0_115.zip`.  Prepare that ZIP once with libhonoka or an equivalent tool,
  then let the backend serve it as an override.

## Example minimal CN config

```toml
[compat]
region = "cn"
cn_main_headers = false
cn_autocreate_ghome_users = true
cn_wrappers = true
cn_optional_stubs = false
# IANA timezone used for date-bound rotations. "auto" means Asia/Shanghai
# in CN mode and Asia/Tokyo otherwise. Use "system" only if you explicitly
# want the host OS timezone to define the game day.
daily_rotation_timezone = "auto"
live_continue_loveca_cost = 1

[download]
backend = "cn_archive"
send_patched_server_info = false

[download.cn_archive]
android_archives = "D:/SIF1_CN/list_CN_Android"
ios_archives = ""
android_extracted = ""
ios_extracted = ""
db_root = "D:/SIF1_CN/db"
application_version = "9.7.1"
client_version = "97.4.6"
update_package_type = 99
server_info_override = "99_0_115.zip"
android_server_info_override = "D:/SIF1_CN/99_0_115_Termux.zip"
ios_server_info_override = ""
```

## About `99_0_115.zip`

CN packages contain `config/server_info.json`, and that file is encrypted by the
client resource format.  honoka-chan's documented deployment flow is to decrypt
an existing server-info package with libhonoka, replace the original Shanda/SDO
host with your private server host, re-encrypt it, and publish it as
`99_0_115.zip`.  The CN client then downloads it last during `/download/update`,
so it overwrites the original endpoint config.

This branch follows that idea without mutating your raw archive mirror:

1. Put the original CN archives in `android_archives` / `ios_archives`.
2. Keep `send_patched_server_info = false` for CN mode.
3. Either place your patched file directly in the archive directory as
   `99_0_115.zip`, or set `android_server_info_override` /
   `ios_server_info_override` to a prepared patched ZIP.  The backend serves that
   file under the URL name `99_0_115.zip` and prefers it over any same-named raw
   archive file.

`db_root` must contain the database files NPPS4 expects, such as
`game_mater.db_`, `unit.db_`, `live.db_`, `item.db_`, `scenario.db_`, etc.  The
raw ZIP archive folder is enough for client download URLs, but not enough for
NPPS4's ORM to load master data.

## Daily / random live rotation

NPPS4 already had a real `special_live_rotation_m` implementation, so the CN
branch does **not** port honoka's live schedule wholesale.  Instead, CN mode now
keeps NPPS4's master DB and live status system, but computes date-bound rotation
in a configured game timezone and exposes both the current and next rotation
window, which mirrors honoka-chan's observed CN behavior.  The default CN game
timezone is `Asia/Shanghai`; this is a timezone conversion from the current UTC
instant, not `local_time + 8 hours`, so it will not double-add eight hours on a
host that is already set to China/Hong Kong time.  Normal JP/Global mode still
defaults to `Asia/Tokyo`.

Set `[compat].daily_rotation_timezone = "system"` only if you intentionally want
the deployment machine's local timezone to define daily rotation boundaries.  For
portable servers, leave it as `auto` or set an explicit IANA name such as
`Asia/Shanghai`.

`rlive/*` is now a safe wrapper rather than an optional stub: `rlive/lot` chooses
a valid random-live candidate from NPPS4's normal/special live tables, stores a
temporary token mapping, and `rlive/play` / `rlive/reward` call NPPS4's real
`live/play` and `live/reward` logic.  `rlive/continue` delegates to the same real `live/continue` cost/state path.

## Recommended test order

1. Start with `cn_optional_stubs = false`.
2. Verify GHome handshake/login, then `/main.php/login/authkey` and
   `/main.php/login/login`.
3. Verify `/download/update` appends the prepared `99_0_115.zip` and that the
   client continues using your private server host.
4. Let real missing endpoints fail loudly; add real implementations one by one
   using NPPS4 as the gameplay source of truth and honoka only as a field-level
   request/response reference.
5. Turn on `cn_optional_stubs = true` only when you need to pass a non-critical
   UI screen temporarily while collecting logs.


See `CN_COMPAT_MATRIX.md` for the keep/wrapper/extend/stub decision matrix.


## v8 notes

- `greet/user`, `greet/delete`, `notice/noticeFriendGreeting`, and `notice/noticeUserGreetingHistory` are now backed by a real `user_greet` table instead of optional stubs.
- `login/topInfo` now reports pending friend requests and unread greetings from NPPS4 state.
- `eventscenario/startup` and `multiunit/scenarioStartup` moved from optional stubs to safe CN wrappers because they are entry handshakes and do not mutate gameplay state.
- Accessory endpoints (`unit/accessoryAll`, `unit/accessoryTab`, `unit/accessoryMaterialAll`, `unit/wearAccessory`, `unit/favoriteAccessory`) are now backed by persistent `user_accessory`, `user_accessory_wear`, and `user_accessory_material` tables.
- `reward/sellUnit`, `live/continue`, and `rlive/continue` are implemented as real state-backed paths in v10; optional stubs no longer cover these.


## v9 accessory notes

The CN accessory endpoints are now real NPPS4 state, not optional stubs:

- `unit/accessoryAll` reads owned accessories and wearing state.
- `unit/accessoryMaterialAll` reads accessory-material quantities.
- `unit/accessoryTab` returns the standard SIF accessory tab layout, or an operator-supplied `accessory_tab_list.json` when present.
- `unit/wearAccessory` validates both the unit and the accessory owner, then enforces one accessory per unit and one unit per accessory.
- `unit/favoriteAccessory` persists the favorite flag.
- rewards with `add_type = 1002` (`ACCESSORY`) now grant accessories/materials through the NPPS4 reward path.
- equipped accessory smile/pure/cool values from `accessory_m` are added to live deck stats before SIS/leader calculations.

This intentionally does **not** copy honoka-chan's default full-UR/full-favorite behavior. Accessories are owned when the account or reward flow grants them, preserving NPPS4's progression model.

Upgrade from v8 requires the `cn_accessories` Alembic migration.

## v10 continue / reward sell notes

`live/continue`, `rlive/continue`, and `reward/sellUnit` are now real state-backed paths rather than optional stubs:

- `live/continue` verifies that the user has a current `live_in_progress` row, deducts `[compat].live_continue_loveca_cost` Loveca, and keeps the live session active so the later `live/reward` path still uses NPPS4's original live-clear logic.
- `rlive/continue` validates the random-live token and then delegates to the same `live/continue` implementation, avoiding a separate random-live continue state machine.
- `reward/sellUnit` can sell UNIT incentives directly from the present box, remove those incentives, grant game coins, and award sticker/exchange points when applicable.  If a regular `unit/sale`-shaped request is routed here, it also performs a real owned-unit/support-member sale instead of returning a fake no-op.

The compatibility option `cn_optional_stubs` is now only a debugging hook; this build no longer registers any no-op handlers there by default.

New config option:

```toml
[compat]
live_continue_loveca_cost = 1
```
