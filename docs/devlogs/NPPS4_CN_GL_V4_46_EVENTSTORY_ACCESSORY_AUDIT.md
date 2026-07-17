# NPPS4 CN/GL v4.46 event-story and accessory audit

## Scope

This audit compares:

- the v4.45/v4.46 NPPS4 fork;
- the supplied latest `honoka-chan-dev` source;
- the supplied CN 9.7.1 client Lua contract;
- the supplied CN and GL decrypted `unit` master databases.

The objective is to preserve NPPS4's stateful architecture, use honoka-chan only where it provides useful CN protocol evidence, and keep the new accessory logic usable with both CN and GL profiles.

## 1. Event-story provenance

The fork's event-story implementation is **not a direct port of honoka-chan**.

### honoka-chan implementation

The supplied latest honoka-chan source implements only:

- batched `eventscenario/status`;
- direct `eventscenario/startup` with an empty startup payload.

Its status handler:

- reads CN `event_scenario_m`;
- returns every chapter with hardcoded `status=2`;
- returns no per-user read/completion state;
- applies two CN historical banner remaps (`10001 -> 38`, `221 -> 215`).

It does not implement real `open`, `reward`, per-user persistence, or replay protection.

### fork implementation

The fork borrowed only the CN response shape and the two proven banner remaps. It added independently:

- `EventScenarioUnlock` per-user database state;
- `eventscenario/status` based on real unlock rows;
- `eventscenario/open` and new/read state transitions;
- `eventscenario/startup` with validated chapter metadata;
- `eventscenario/reward` with completion state and replay protection;
- post-service archive provisioning.

### current CN limitation

The player-state layer is generic, but `game/eventscenario.py` currently reads masters through `cn_content_master`. Therefore the current implementation is operational for CN but the master-data provider is still CN-bound.

For future GL support, the correct change is:

1. keep the existing endpoint and per-user state logic;
2. introduce an active-profile event-scenario master provider;
3. read CN masters from the CN archive and GL masters from the active GL split database/archive;
4. keep only profile-specific asset-path quirks in adapters.

LLSIF@Home may be useful as a secondary behavior oracle, but it is not required. The GL client contract plus the GL master database and NPPS4's stateful model are sufficient primary inputs.

## 2. Latest honoka-chan accessory completeness

The latest supplied honoka-chan source implements only a partial accessory shell.

| Operation | honoka-chan state |
|---|---|
| `accessoryAll` | Implemented, but hardcodes every item to level 8, max level 8, remake count 4, favorite=true |
| `accessoryMaterialAll` | Returns an empty list |
| `accessoryTab` | Loads a static JSON list |
| `wearAccessory` | Persists wear rows with limited validation |
| `favoriteAccessory` | Prints the request and returns success; does not persist |
| `createAccessory` | Missing |
| `mergeAccessory` | Missing |
| `saleAccessory` | Missing |

Therefore honoka-chan does not implement the full accessory economy or progression cycle.

## 3. Client contract recovered from CN Lua

The supplied CN client calls:

- `POST /unit/createAccessory` with `unit_owning_user_ids`;
- `POST /unit/mergeAccessory` with `base_accessory_owning_user_id`, `accessory_owning_user_ids`, `material_list`, and `merge_type`;
- `POST /unit/saleAccessory` with `accessory_owning_user_ids` and `material_list`.

The client consumes these response fields:

- creation: `reward_box_flag`, `created_accessory`, `unit_removable_skill.owning_info`;
- merge: `before`, `after`, `gain_exp`, `rank_up_count_after`, `is_enough`, `rest_exp`;
- sale: sale total and normal user/reward-box state.

The client model also establishes:

- enhancement purpose = 1;
- remake/overcome purpose = 2;
- maximum remake count = 4;
- Glass Parts (`effect_type=1`) are enhancement materials;
- Jewel Parts (`effect_type=2`) are remake materials;
- ordinary remake fodder must have the same `accessory_id` as the base;
- one same-ID accessory contributes one remake;
- Jewel Part remake contribution is `floor(selected amount / required amount)`;
- max level rises by one per remake, up to the master maximum;
- level thresholds in `accessory_level_m.next_exp` are cumulative.

## 4. CN/GL master compatibility

The exact CN and GL databases have identical schemas for all core accessory tables:

| Table | CN rows | GL rows | Schema compatible |
|---|---:|---:|---|
| `accessory_base_setting_m` | 1 | 1 | yes |
| `accessory_m` | 336 | 562 | yes |
| `accessory_level_m` | 4895 | 8511 | yes |
| `accessory_level_limit_over_m` | 12 | 12 | yes |
| `accessory_lottery_cost_m` | 21 | 21 | yes |
| `accessory_lottery_group_m` | 9 | 9 | yes |
| `accessory_lottery_list_m` | 288 | 288 | yes |
| `accessory_special_m` | 258 | 484 | yes |

The GL database contains more accessories and special-card mappings, but the same algorithms and fields apply. v4.46 reads the active profile through `context.db.unit`, rather than embedding CN-only accessory IDs or tables.

## 5. v4.46 implementation

v4.46 adds or completes:

- persistent `rank_up_count` on `UserAccessory`;
- exact accessory level, current level cap, next EXP, capped overflow EXP, and current stats;
- inventory and material capacity enforcement;
- real special-create detection;
- persistent favorite state;
- validated and idempotent wear state;
- card-to-accessory creation using:
  - `accessory_special_m` for a single mapped card;
  - otherwise official rarity/level/skill lottery costs, groups, active weighted lists;
- card and coin consumption during creation;
- enhancement with ordinary accessories and Glass Parts;
- remake with same-ID accessories and Jewel Parts;
- multiple remakes in a single valid request;
- current-level merge costs, grant EXP, sale prices, and stat differences;
- sale of ordinary accessories and material stacks;
- normal coin-cap/present-box handling;
- rejection of favorite or equipped accessories as fodder/sale items;
- rejection of favorite, partner, or accessory-wearing cards for creation;
- `unit/createAccessory`, `unit/mergeAccessory`, and `unit/saleAccessory` endpoints.

## 6. Database and CN master changes

- Alembic revision `accessory_full_cycle` upgrades from v4.45 revision `cn_post_service_content` and adds `user_accessory.rank_up_count` with default 0.
- The exact CN accessory tables are bundled in `cn_client_master.db`.
- The CN split-master generator is bumped to `cn_honoka_master:v6_accessory_full_cycle`.
- Exact CN generation produces all 336 accessories, including 10 material rows whose nullable client attributes are normalized only where the NPPS4 target schema requires a non-null value.

## 7. Validation

Executed against both exact CN and GL unit masters:

- single-card special creation;
- multi-card normal lottery creation;
- card and coin consumption;
- equip and remove persistence;
- enhancement with Glass Parts;
- ordinary-accessory EXP fodder;
- capped EXP preservation;
- same-ID remake;
- batch Jewel Part remake;
- persistent favorite protection;
- ordinary accessory sale;
- material-stack sale;
- material-class rejection.

Both profiles completed the same lifecycle successfully. The generated CN split DB contains the expected full accessory table counts. Clean Alembic creation and v4.45-to-v4.46 upgrade both reach `accessory_full_cycle` with the new column present.

## 8. Remaining uncertainty

The implementation is source-, client-, and master-data-grounded, and its database lifecycle is integration-tested. It has not yet been exercised through the real CN or GL game UI. Final device testing should cover:

- creating a special accessory;
- creating a normal lottery accessory;
- enhancement;
- remake;
- sale;
- favorite and wear behavior;
- UI response rendering.

No GL event-story provider refactor is included in v4.46; that remains a separate future change.
