# NPPS4 CN v4.41 audit: log27, log28 and original-server behaviour

## Evidence boundary

The changes in v4.41 are based on four cross-checked sources:

1. v4.40 device logs (`sif_cn_full_log27.txt`, `sif_cn_full_log28.txt`);
2. original NPPS4 source and the v4.34-v4.40 modification history;
3. the supplied CN 9.7.1 and community clients;
4. the exact CN client master database, with honoka-chan used only as a CN
   compatibility reference where NPPS4 has no implementation.

## Announcement

v4.40 returned a single supported type-2 banner, proving the previous type-18
fatal was removed. The remaining failure occurred only when the card was
flipped. The original NPPS4 source and the user's original-server screenshots
show that Swagger at `/main.php/api` is deliberately the in-game announcement,
not an accidental debug leak. v4.41 therefore restores that original route and
uses the CN archive's unprefixed poster asset path.

The asset-path diagnosis is strongly constrained by the front side rendering
normally and the crash occurring only when the back-side poster is created,
but it remains device-unverified.

## Live start

log28 repeatedly shows `/main.php/live/play` rejected with HTTP 422 and
`X-Message-Code does not match`. The game handler therefore never ran. The
client's native CN CROSS digest does not match NPPS4's JP/GL key domain, and the
secret is not available in either server source.

v4.41 does not disable XMC globally and does not fake a successful Live. It
keeps token authentication, then bypasses only CN CROSS verification for an
already-authenticated session. SHARED XMC and all non-CN clients continue to
use original NPPS4 verification. This lets the real `live/play` logic expose
any subsequent gameplay/schema issue instead of being blocked at HTTP input.

## Content availability

The old CN master conversion reduced important tables. The exact client overlay
contains, among other data:

- 6,399 achievements with the full 31-column schema;
- 1,894 Live settings and 366 Live tracks;
- 445 main scenarios;
- 711 event-story chapters;
- 50 multi-unit story chapters.

The exact achievement data contains final-service release/login achievements
whose rewards correspond to the original NPPS4 screenshots (mass song and story
unlock popups). v4.41 adds missing eligible achievement rows, then uses the
ordinary NPPS4 login checker and reward processor. It does not synthesize the
popup list or directly mark ordinary progression achievements complete.

Event and multi-unit archives have no surviving scheduler, so they use new
real per-user state tables and actual status/startup/reward endpoints. They are
made replayable once, without restoring expired event-point or ranking rewards.

## Runtime regression results

A clean configured SQLite workspace was used for dynamic import and execution:

- all routes imported without duplicate registration;
- one sync inserted 711 event rows, 50 multi-unit rows and one grant marker;
- a second sync inserted nothing;
- the normal login achievement checker returned 72 completed and 6 new
  achievements;
- reward processing completed and produced 28 Live plus 48 Scenario reward
  items in the test account;
- `lbonus/execute`, event status/startup and multi-unit status/startup all built
  valid Pydantic responses.

The remaining integration tests are the actual CN poster flip and a complete
Live start/play/finish cycle on device.
