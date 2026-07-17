# v4.39 history + client-contract invariant repair

This release is based on a cross-check of upstream NPPS4, honoka-chan, modified versions v4.33-v4.38, the CN 9.7.1 client, the community 9.11 client, and log21-log25.

## Changes backed by client bytecode and version history

- Centralize CN onboarding snapshot/repair/mutation logic in `npps4.system.onboarding`.
- Repair only the exact v4.34-v4.37 completed-but-empty account shape.
- Keep NPPS4's real 0 -> 1 -> 2 -> 3 -> -1 tutorial state machine.
- Require the exact client field `tutorial_state`; remove speculative aliases, wrapper guessing and inferred transitions.
- Before `login/unitSelect` returns success, verify:
  - deck 1 contains nine valid active owning IDs;
  - deck master IDs match the selected starter set in order;
  - the center is deck slot 5 and the expected starter member;
  - album rows exist for all starter members;
  - the expected tutorial state exists.
- Preserve additive v4.37 `item/list` and multi-unit compatibility.
- Do not send banner type 18 to either audited client generation (<= 9.11); both Lua clients lack a type-18 handler. Other NPPS4 banners remain.
- Stop advertising Arena (`0/25` client routes implemented) and the incomplete Costume feature (`1/4` routes implemented). Keep Accessory enabled because it has real partial mutations.
- Keep `open_v98=True` and the existing 9.7.1/97.4.6 version split unchanged; there is no evidence that either should be changed.
- Redact decrypted login credentials and raw bearer tokens from logs.
- Add `tools/cn_contract_guard.py` to prevent regression to previously disproved behavior.

## Validation

- Python syntax compilation passed for Android and PC source trees.
- The CN contract guard passed for both trees.
- Static client/server route analysis found 352 client routes, 134 server routes and 130 covered routes. Missing optional/event routes are documented separately and are not silently presented as complete.

This source build still requires device testing. It must not be claimed to have eliminated the native client crash until the CN client completes onboarding and enters home successfully.
