# v4.46 CN/GL accessory full cycle

This release completes the stateful accessory lifecycle without replacing NPPS4 behavior with honoka-chan's hardcoded shell.

## Event-story provenance audit

- The fork's event-story implementation is not a direct port of honoka-chan.
- honoka-chan was used only as a CN protocol/asset reference, including two historical banner remaps.
- The fork adds its own per-user `EventScenarioUnlock` state and real `status`, `open`, `startup`, and `reward` actions.
- The current master-data provider is still CN-bound (`cn_content_master`). Future GL support should keep the player-state logic and replace the master provider with an active-profile source. LLSIF@Home may be a secondary behavior reference, but is not required for that refactor.

## Latest honoka-chan accessory audit

The latest supplied honoka-chan source implements only a partial shell:

- `accessoryAll` hardcodes level 8, max level 8, remake count 4, and favorite=true.
- `accessoryMaterialAll` returns no material inventory.
- `favoriteAccessory` acknowledges the request but does not persist it.
- `wearAccessory` performs only limited ownership validation.
- `createAccessory`, `mergeAccessory`, and `saleAccessory` are absent.

## v4.46 implementation

The implementation is reconstructed from the CN client Lua contract plus the exact CN and GL accessory master tables:

- persistent inventory, favorite state, material inventory, and wear state;
- exact current level, next EXP, current level cap, remake count, and capped overflow EXP;
- card-to-accessory creation using special-card mappings or the official rarity/level/skill lottery tables;
- card and coin consumption during creation;
- enhancement with ordinary accessories and Glass Parts;
- remake with same-ID accessories and Jewel Parts, including multiple remakes in one request;
- current-level merge costs, grant EXP, sale prices, and stat differences;
- validated wear, consume, favorite, partner, and capacity constraints;
- real `createAccessory`, `mergeAccessory`, and `saleAccessory` endpoints;
- active-profile master access through `context.db.unit`, so the same logic works with CN and GL unit databases.

## Database migration

A new `rank_up_count` column is added to `user_accessory` by Alembic revision `accessory_full_cycle`, upgrading cleanly from v4.45 revision `cn_post_service_content`.

## Test status

The complete create/enhance/remake/favorite/sale flow was executed against both the exact CN and GL unit master databases. Static compilation, clean migration, v4.45-to-v4.46 migration, split-DB generation, schema checks, and Android/PC source parity passed. Client-device testing is still required for final response-shape and UI confirmation.
