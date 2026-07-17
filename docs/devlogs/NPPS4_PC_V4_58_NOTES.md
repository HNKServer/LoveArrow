# v4.58 — CN transfer banner cache-key correction

- Keeps the working CN front/back carousel, manga flip, transfer WebView, 1718 scouting page, native 16-entry Museum unlock, and PC/Android Python parity.
- The data-transfer banner now uses `assets/image/secretbox/icon/s_ba_900001_1.png` as its client cache/download key.
- The server maps that otherwise-unused honoka banner key to the bundled Chinese `数据迁移` image, including the `.imag` form.
- `s_ba_1718_1.png` remains exclusively attached to the real 1718 scouting page.
- The custom image is no longer inserted into `99_0_115.zip`; the 99 update package is again server-info-only.
