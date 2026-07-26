# v5.30：国服精确 Unit Master 补齐

本版以 v5.29 为基线，仅修复国服仍无法识别晚期专用饰品目标卡的问题。

- 国服精确 Unit Master 从旧的 3644 张更新为 honoka-chan 最终 CN 数据中的 3963 张。
- 保留国服本地化字段，并补齐新增卡引用的技能定义。
- 更新 CN client catalogue，使 `unit/unitAll` 与兑换码使用同一套 3963 张能力目录。
- `Unit 3993 [SUNNY DAY SONG] Honoka Kosaka` 已验证可在 CN Profile 下解析。
- 不修改 v5.24 的饰品发放、升级、制作、装备和转移行为。
- 不新增数据库迁移。
