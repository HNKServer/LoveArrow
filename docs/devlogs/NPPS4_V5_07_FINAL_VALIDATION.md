# NPPS4 v5.07 最终自动化验证报告

- 通过：**21**
- 失败：**0**

| # | 结果 | 检查 | 详情 |
|---:|:---:|---|---|
| 1 | PASS | ranking/live bypasses transport XMC verification |  |
| 2 | PASS | ranking/player bypasses transport XMC verification |  |
| 3 | PASS | ranking/player uses error_code 1 safe fallback |  |
| 4 | PASS | guest Live projection validates receiver-side leader skill |  |
| 5 | PASS | partyList advertises validated guest projection |  |
| 6 | PASS | live/play recalculates with the same validated projection |  |
| 7 | PASS | event story null omission fix retained |  |
| 8 | PASS | response remains signed game protocol response |  |
| 9 | PASS | v5.07 build ID present |  |
| 10 | PASS | Android versionCode 507 |  |
| 11 | PASS | Android versionName 0.5.7 |  |
| 12 | PASS | honoka generic fallback is HTTP protocol success with status 600/error 1 |  |
| 13 | PASS | honoka implements ranking/live but not ranking/player |  |
| 14 | PASS | ranking/player empty state returns honoka-compatible game error | (1, 600) |
| 15 | PASS | ranking/live empty state remains honoka-compatible success | {'page': 0, 'rank': 0, 'items': [], 'total_cnt': 0, 'present_cnt': 0} |
| 16 | PASS | guest card with missing receiver-side leader skill is rejected |  |
| 17 | PASS | guest card with valid receiver-side leader skill is accepted |  |
| 18 | PASS | Python compileall succeeds |  |
| 19 | PASS | Android and PC Python trees are identical | 2315 vs 2315 |
| 20 | PASS | CN verified asset unchanged: 4_0_999.zip |  |
| 21 | PASS | CN verified asset unchanged: npps4_data_transfer.png |  |
