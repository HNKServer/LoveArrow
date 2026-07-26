# v5.24：回退未部署的排名数据库实验，保留精确 Master 与纯相册模式

本版以用户实际部署链为准：用户从未运行 v5.21、v5.22 或 v5.23，因此不保留这些版本引入的排名兼容负担。

## 已完全撤回

- `live_clear.profile`
- `live_replay.profile`
- `player_ranking.profile`
- `live_clear.normalized_hi_score`
- CN/GL 分榜逻辑
- CN 固定或动态加权逻辑
- 逐局排名归一化负载
- `shared` 虚拟 Profile 日榜
- Alembic `0010`、`0011`、`0012`
- Android 对上述三次迁移的手工兼容代码

歌曲最高分、精确回放和每日排名恢复为 v5.20 的共享原始分数结构：同一共享账号、同一歌曲只有一条 LiveClear；CN 和 GL 都读取和更新它。

## 继续保留

- 服务端内置 CN/GL 精确 Unit Master，不依赖同机安装的客户端 APK。
- 专用饰品目标 UR 的精确创建和测试码补齐。
- v5.21 后修复的饰品、招募 Detail 与客户端 Master 回退。
- CN/GL 各自的回忆画廊内容与解锁状态。
- 回忆画廊 Smile/Pure/Cool 永久加成默认关闭，只作为相册使用。

## 数据库前提

本版没有新增数据库迁移，Alembic head 恢复为 `costume_full_cycle`。它面向从未运行 v5.21–v5.23 的实际数据库，可直接沿用 v5.20 及更早正常迁移后的玩家数据。

如果某个第三方数据库已经实际升级到 `profile_ranking_state` 或其后版本，应先恢复升级前备份；本版不会为从未部署的实验结构继续增加反向迁移。
