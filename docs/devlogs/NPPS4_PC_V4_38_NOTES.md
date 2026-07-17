# v4.38 CN onboarding state repair

This release fixes the source-level state corruption identified in log25 while preserving NPPS4 as the authoritative implementation.

## Root cause fixed

v4.34-v4.37 marked `tutorial_state=-1` before `login/unitSelect` created the selected starter units and deck.  The endpoint then returned HTTP 200 without performing the mutation.  The CN client subsequently received empty `unit/deckInfo` and `album/albumAll` data and its Lua home/tutorial code aborted through `CLuaState`/SIGTRAP.

## Changes

- Restore NPPS4's real tutorial transitions: `0 -> 1 -> 2 -> 3 -> -1`.
- `login/unitSelect` now creates/reuses the selected nine units, idolizes and sets the center, and saves deck 1 before returning success.
- CN retries are idempotent: partial mutations are repaired by creating only missing units, not by skipping the operation.
- Remove the login/userInfo shortcuts which automatically marked any account with units as tutorial-complete.
- Repair the exact broken v4.34-v4.37 account state (`tutorial_state=-1`, zero active units, no deck, no center) back to state 0 on login/progress.
- Keep upstream NPPS4 behavior unchanged for non-CN clients.
- Improve CN batch diagnostics to include nested list/dict sizes.

No masterdata, archive download, WebUI translation, reward, friend-system, or unrelated game-feature implementation was replaced.
