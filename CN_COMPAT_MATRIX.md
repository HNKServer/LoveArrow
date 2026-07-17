# CN compatibility matrix

Goal: keep NPPS4 as the gameplay source of truth and only add the smallest CN
compatibility layer needed by the `klb.android.lovelivecn` client.

## Decision rules

Do **not** port a honoka-chan handler just because the file/action name is not
present in NPPS4. Classify each CN-only action by semantics:

| Strategy | Meaning | Default |
|---|---|---|
| `keep_npps4` | NPPS4 already implements the gameplay action. Do not touch it. | on |
| `cn_backend_only` | Same action name, but CN uses different download/config source. Replace backend only. | on |
| `cn_auth_bridge` | CN SDK/auth action before `/main.php`; bridge it to NPPS4 users. | on |
| `wrapper_to_npps4` | CN action name differs, but NPPS4 has the same underlying system. Add a thin wrapper. | on |
| `extend_npps4_system` | Feature exists conceptually, but NPPS4 lacks persistent state. Build it in `npps4/system`, not as a stub. | on when implemented |
| `optional_stub` | Temporary no-op/empty response used only to get farther logs. Must be opt-in. | off |
| `do_not_port` | honoka behavior weakens or bypasses original gameplay. Do not port. | off |

## Always necessary for CN client startup

| Area | Implementation | Why |
|---|---|---|
| GHome/Shengqu endpoints | `npps4/ghome/router.py` | CN client talks to SDK/account endpoints before SIF `/main.php`. |
| GHome credential bridge | `userid + ticket` becomes NPPS4 `login_key + password` | Keeps NPPS4 `/login/login` verification intact. |
| CN raw archives | `npps4/download/cn_archive.py` | Your data mirror is flat `list_CN_Android/*.zip`, not NPPS4 internal archive-root. |
| `99_0_115.zip` override | `android_server_info_override` / `ios_server_info_override` | Only this encrypted `config/server_info.json` package should be patched; other packages stay original. |
| `package_type=0 -> 4` in batch | CN archive backend | CN first-download quirk documented in honoka-chan. |
| wide `LANG` parsing | `idoltype.normalize_language` and raw header strings | Avoids 422 when CN client sends non-`en/jp` language codes. |

## Same-name or same-semantics actions: keep NPPS4

These should remain NPPS4-owned. CN compatibility should adjust only request
normalization, download backend, language fallback, or tiny response-shape issues.

| Action | Strategy |
|---|---|
| `login/authkey`, `login/login` | `cn_auth_bridge`, keep NPPS4 login logic |
| `download/update`, `download/batch`, `download/additional`, `download/getUrl` | `cn_backend_only` |
| `live/play`, `live/gameover`, `live/reward` | `keep_npps4` |
| `secretbox/pon`, `secretbox/multi` | `keep_npps4` |
| `unit/deck`, `unit/deckName`, `unit/unitAll`, `unit/wait`, `unit/merge`, `unit/sale` | `keep_npps4` |
| `reward/rewardList`, `reward/open`, `reward/openAll` | `keep_npps4` |
| `scenario/startup`, `scenario/reward`, `subscenario/startup`, `subscenario/reward` | `keep_npps4` |
| `payment/productList`, `payment/receipt` | keep NPPS4 game payment; GHome product list is separate |

## CN wrappers that may be safe by default

These should be implemented as thin wrappers over NPPS4 systems, not copied from
honoka-chan.

| CN action | NPPS4 source of truth | Status in this build |
|---|---|---|
| `achievement/pagingAccomplishedList` | `system.achievement` accomplished achievement state | implemented in `cn_wrappers.py` |
| `rlive/lot`, `rlive/play`, `rlive/gameover`, `rlive/reward` | NPPS4 normal/special live DB plus `live/play` / `live/reward` | implemented as token wrapper in `cn_wrappers.py` |
| CN special daily schedule | `special_live_rotation_m` plus NPPS4 live status | implemented in `system.live` / `game.live`; CN defaults to configured game timezone `Asia/Shanghai`, not manual `+8h` |

## CN-only actions that need real NPPS4 system work

Do not leave these as default empty responses. Either build real persistence in
`npps4/system`, or keep them disabled until logs prove they are needed.

| CN action | Likely NPPS4 system extension |
|---|---|
| `friend/request`, `friend/response`, `friend/expel`, `friend/requestCancel`, `friend/list` | implemented in v7 with shared `friend_link` table; CN and global users can interoperate |
| `greet/user`, `greet/delete`, `notice/noticeFriendGreeting`, `notice/noticeUserGreetingHistory` | greeting/message storage plus notice integration |
| `unit/accessoryTab`, `unit/accessoryMaterialAll`, `unit/wearAccessory`, `unit/favoriteAccessory` | now backed by NPPS4 accessory tables; no longer optional stubs |
| `rlive/continue` | implemented in v10; validates token, then delegates to `live/continue` |
| `live/continue` | implemented in v10; verifies current live and deducts configurable Loveca cost |
| `reward/sellUnit` | implemented in v10; sells present-box UNIT incentives or regular sale-shaped requests |

## Shared NPPS4 system extensions implemented

| Area | Status | Notes |
|---|---|---|
| Friend request/approval/list | implemented in v7 | `friend_link` stores directional states; CN and global/community accounts share one friend graph. |
| Greeting/notice history | implemented in v8 | `user_greet` backs sent/received greeting state and topInfo counts. |
| Accessory ownership/equipment | implemented in v9 | `user_accessory`, `user_accessory_wear`, and `user_accessory_material` back accessory endpoints and live deck stats. |
| Live continue / reward sell-unit | implemented in v10 | Uses NPPS4 live-in-progress, Loveca, present-box incentive, unit sale, coin, and exchange-point state. |

## Temporary opt-in stubs

`cn_optional_stubs.py` exists for log discovery only. Enable it with:

```toml
[compat]
region = "cn"
cn_optional_stubs = true
```

Do not use successful gameplay tests from this mode as proof of correctness; it
may hide missing systems.


## v8 notes

- `greet/user`, `greet/delete`, `notice/noticeFriendGreeting`, and `notice/noticeUserGreetingHistory` are now backed by a real `user_greet` table instead of optional stubs.
- `login/topInfo` now reports pending friend requests and unread greetings from NPPS4 state.
- `eventscenario/startup` and `multiunit/scenarioStartup` moved from optional stubs to safe CN wrappers because they are entry handshakes and do not mutate gameplay state.
- Accessory endpoints are now persistent NPPS4 state (`user_accessory`, `user_accessory_wear`, `user_accessory_material`) instead of optional stubs.
- v10 implements `reward/sellUnit`, `live/continue`, and `rlive/continue` as real state-backed paths; optional stubs no longer provide no-op fallbacks for them.
