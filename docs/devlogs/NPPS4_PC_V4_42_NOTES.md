# v4.42 — CN manga banner and Android Wrapper UI

This revision preserves the v4.41 gameplay/content fixes and adds only grounded changes:

- CN type-2 home banner now uses a banner asset path already used by honoka-chan with the CN client (`assets/image/secretbox/icon/s_ba_1718_1.png`) instead of the missing `wv_ba_01.png`; its WebView opens the bundled official mini-comic gallery at `/manga`.
- The legacy type-2 card remains `back_side=true`, so the client's built-in data-transfer front and the poster back are preserved. Existing NPPS4 `handover/*` and `/ewexport` implementations are not replaced.
- The complete honoka-chan mini-comic HTML/static image set is bundled into NPPS4's ordinary `/static` workspace.
- Android Wrapper no longer creates a one-line `login_bonus.py` placeholder. Missing or old placeholder files are backed up and replaced with the full upstream three-day reward script.
- Text editors keep vertical/horizontal scrollbars visible instead of fading them out.
- The main Wrapper screen uses a two-column card grid in landscape and a single column in portrait; subpages stay single-column.

Not claimed as solved in this revision:

- Secretbox poster/background completeness still depends on the CN CDN archive containing the referenced recruitment assets. The server already returns four real secretbox categories; v4.42 does not fabricate poster data.
- A complete Memories Gallery requires the full GL museum master database plus the corresponding GL CDN assets. Those are not contained in either client APK. v4.42 does not replace the CN museum with fake rows or unlock everything indiscriminately.
