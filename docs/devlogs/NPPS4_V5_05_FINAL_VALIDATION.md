# NPPS4 v5.05 最终验证报告

Build ID：`v5.05-museum-profile-ranking-fix`

## 结果

- v5.05 定向验证：**40 通过，0 失败**。
- v5.04 好友/Profile/Live/Profile 识别回归：**47 通过，0 失败**。
- 自动化断言合计：**87 通过，0 失败**。
- Android、PC Python 树：各 **2315** 个文件，逐文件一致（忽略缓存）。
- Android、PC `compileall`：通过。
- Android、PC CN contract guard：通过。

## Museum 审计

- 原始 NPPS4 的 `TEST_MUSEUM_UNLOCK_ALL` 默认为关闭。
- 在原始 NPPS4 Python 运行代码中，`museum.unlock()` 只有两个实际写入口：通用 `ADD_TYPE.MUSEUM` 奖励处理和 LILA 存档导入；打歌、剧情、等级、招募、普通每日签到代码没有直接 Museum 解锁调用。
- honoka-chan 的 CN Master `museum_contents_m` 有 **16** 项，其接口直接遍历全部原生行。
- LLSIF@Home 的 GL `museum_info.json` 有 **1360** 项，其实现同样直接返回整套目录。
- v5.05 将 `museum_unlock_policy = "normal" | "all"` 上移为 CN、GL 各自独立的 Profile 配置，默认均为 `all`。
- `all` 只读取当前请求 Profile 的原生 Museum Master；不会把 GL 1360 项移植到 CN，也不会反向移植 CN 条目。
- `normal` 状态按 `(user_id, profile, museum_contents_id)` 隔离。
- 旧数据库没有 Profile 信息，因此升级时把旧共享解锁记录同时保留到 CN、GL；请求时仍由本服 Master 过滤无效 ID。

## 独占卡资料回退

- 主页卡和伙伴卡都会先尝试原选择。
- 接收端 Master 不存在该卡时，继续尝试另一张选择卡。
- 两张选择卡都属于对方服独占时，会扫描该账号仍处于 active 状态的库存，按收藏、绊值、拥有 ID 的稳定顺序选择第一张接收端可识别的卡。
- 好友列表、搜索、问候、新消息、个人资料、Live 助战和 Ranking 共用同一代表卡投影逻辑。
- 动态测试已覆盖“两张首选中包含独占卡，回退到共同卡”的执行路径。

## Ranking 安全空处理

- `ranking/player` 的非零 `id` 不再被当成数据库用户主键；它表示查询当前玩家位置。
- 空榜、未上榜和负页码都返回成功结构：`rank=0`、`items=[]`、`total_cnt=0`。
- `ranking/live` 和 `ranking/player` 都执行了动态空榜响应测试。
- Live 和每日榜增加稳定并列顺序及当前用户名次计算。
- 排名条目复用跨服代表卡投影；无法安全表示的异常条目会被跳过，不向客户端发送不存在的 Master ID。

## 数据库升级验证

- Android schema upgrader 已对旧版无 `profile` 的 `museum_unlock` 表实际执行。
- Alembic `_sqlite_upgrade` 已从迁移源码 AST 直接执行于旧结构 SQLite 数据库。
- 两条路径均生成 CN、GL 两份兼容记录和 `(user_id, profile, museum_contents_id)` 唯一约束。
- Android 内嵌 Alembic Payload 已重新生成，共 **28** 个文件，并确认包含最新版 v5.05 迁移。

## 未改动的已验证 CN 资源

- `npps4_data_transfer.png`：`08e658be3c2cc43e4b79a1974da0930da655ea829badef4bafd2a5396c6f4520`
- `4_0_999.zip`：`3d20e352095d450662fc4b736e7156d5ef007c717ffd882adfd4a996f174af2b`

两者与 v5.04 逐字节一致。

## 尚未由当前环境完成

- 未运行完整 Android SDK/Gradle/Kotlin 构建。
- 未进行真机 Museum、跨服独占卡主页和 Ranking UI 测试。
- 当前主机缺项目所需的 `Cryptodome`，未启动完整桌面服务执行 Alembic CLI；但迁移函数和 Android 升级器已经绕过应用导入，直接对旧结构数据库执行通过。
