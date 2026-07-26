# NPPS4 v5.06 最终自动化验证报告

## 汇总

- 通过：**34**
- 失败：**0**

## 检查项

| # | 结果 | 检查 | 详情 |
|---:|:---:|---|---|
| 1 | PASS | eventscenario/status excludes JSON null recursively |  |
| 2 | PASS | endpoint serializer recursively applies exclude_none to Pydantic response models |  |
| 3 | PASS | batch API forwards endpoint exclude_none into serializer |  |
| 4 | PASS | nullable chapter_asset remains optional but is omitted when absent |  |
| 5 | PASS | invented event_scenario_se_btn_asset field removed |  |
| 6 | PASS | CN special event banner remap retained |  |
| 7 | PASS | GL final event 221..228 banner remap implemented |  |
| 8 | PASS | banner path has canonical single suffix |  |
| 9 | PASS | CN event catalogue count unchanged | 711 |
| 10 | PASS | GL event catalogue count unchanged | 755 |
| 11 | PASS | CN contains 546 legitimate NULL chapter assets |  |
| 12 | PASS | GL contains 595 legitimate NULL chapter assets |  |
| 13 | PASS | CN projected status contains no JSON null values |  |
| 14 | PASS | GL projected status contains no JSON null values |  |
| 15 | PASS | CN projects exactly 103 event groups | 103 |
| 16 | PASS | GL projects exactly 109 event groups | 109 |
| 17 | PASS | CN special event uses banner 38 |  |
| 18 | PASS | GL latest event uses existing banner 222 |  |
| 19 | PASS | LLSIF@Home final GL oracle has 109 event groups | 109 |
| 20 | PASS | GL event IDs match LLSIF@Home final archive | 109 vs 109 |
| 21 | PASS | All GL banner assets match LLSIF@Home final archive | [] |
| 22 | PASS | All GL chapter_asset presence/values match LLSIF@Home | [] |
| 23 | PASS | LLSIF@Home never emits event_scenario_se_btn_asset |  |
| 24 | PASS | LLSIF@Home omits absent chapter_asset instead of JSON null |  |
| 25 | PASS | honoka-chan chapter_asset uses omitempty |  |
| 26 | PASS | honoka-chan response has no selected-banner field |  |
| 27 | PASS | honoka-chan proves CN 10001->38 and 221->215 |  |
| 28 | PASS | v5.06 build ID present |  |
| 29 | PASS | Android versionCode 506 |  |
| 30 | PASS | Android versionName 0.5.6 |  |
| 31 | PASS | Android/PC Python trees match | 2315 vs 2315 |
| 32 | PASS | v5.05 verified CN asset unchanged: 4_0_999.zip |  |
| 33 | PASS | v5.05 verified CN asset unchanged: npps4_data_transfer.png |  |
| 34 | PASS | Python compileall succeeds |  |

## 额外执行

- Android CN contract guard：OK
- PC CN contract guard：OK
- Android Python compileall：OK
- PC Python compileall：OK

## 验证边界

这些检查覆盖响应契约、批量 API 的 `exclude_none` 传递、CN/GL Master Data、LLSIF@Home/honoka-chan 对照、源码一致性和语法编译；当前环境不能替代真实 CN/GL 客户端的逐条点击与资源下载验证。
