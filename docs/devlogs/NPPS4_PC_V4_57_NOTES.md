# v4.57 — CN data-transfer cover and 1718 scouting banner

- Installs the Chinese “数据迁移” cover as `assets/image/webview/npps4_data_transfer.png` inside the existing dynamic `99_0_115.zip`; no 116/117 package and no version bump in the CN content protocol.
- The transfer WebView banner now references that dedicated asset instead of stealing `s_ba_1718_1.png`.
- Restores `s_ba_1718_1.png` as an independent type-1 home banner. Its target ID is 1718 and the matching μ's Thank-You Festival scouting page is present in `secretbox/all`.
- Keeps the working back-side `wv_ba_01.png` / `/manga` contract and native 16-item Museum unlock.
- Android and PC Python server trees are identical.
