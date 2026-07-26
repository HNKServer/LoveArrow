# NPPS4 v5.24 最终静态与模拟验证

Build ID：`v5.24-ranking-schema-rollback-museum-visual-only`

- 包类型：PC
- Android 版本：`versionCode 524`、`versionName 0.5.24`
- Alembic head：`costume_full_cycle`
- 新数据库迁移：无
- 内嵌 Python 文件：2340

## 已验证回退

- `LiveClear` 不含 `profile` 与 `normalized_hi_score`。
- `LiveReplay` 不含 `profile`。
- `PlayerRanking` 不含 `profile`。
- 歌曲最高分、精确回放与每日榜恢复为共享账号的原始结构。
- 不存在 CN 固定加权、动态归一化、`shared` 虚拟 Profile 或逐局排名补偿负载。
- Alembic `0010`、`0011`、`0012` 及 Android 对应手工迁移已删除。

## 继续保留

- 服务端只读内置 CN 3644 张、GL 3998 张精确 Unit Master。
- 专用饰品目标卡精确创建和测试码补齐。
- 回忆画廊内容与解锁保留，Smile/Pure/Cool 永久加成默认关闭。
- v5.20 以后与排名数据库无关的饰品、招募、中文配置和跨服投影修复。

## 验证方式

`tools/validate_v524.py` 已通过；完整 Python `compileall` 已通过。由于当前容器未安装项目运行依赖 `pycryptodomex`，没有在此容器执行完整 FastAPI 服务启动；Android Gradle APK 也未在此环境构建。
