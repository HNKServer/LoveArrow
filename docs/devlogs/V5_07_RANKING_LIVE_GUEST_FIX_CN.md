# NPPS4 v5.07：Ranking 安全回退与跨服好友助战校验

## Ranking 的真实故障

v5.06 的 `ranking/live` 与 `ranking/player` 仍采用 NPPS4 默认的 SHARED X-Message-Code 校验。实际客户端的 Ranking 请求会在进入处理器之前得到 HTTP 422：

```json
{"detail":"X-Message-Code does not match"}
```

客户端将 HTTP 级失败当成传输错误，连续重试五次后要求重启。此前加入的空榜结构因此根本没有被执行。

honoka-chan 的行为分为两部分：

- `ranking/live` 有真实处理器；空榜返回 HTTP 200 的成功结构；
- `ranking/player` 没有处理器；通用 NoRoute 返回签名游戏错误 `status_code=600, error_code=1`，客户端只显示一次“请联系客服”，不会按网络故障重试。

v5.07 对两个 Ranking 路由关闭传输层 XMC 校验。`ranking/live` 保留空榜成功；`ranking/player` 在没有日榜数据或参数不受支持时返回与 honoka-chan 通用回退相同的签名 HTTP-200 游戏错误。若数据库以后有真实日榜数据，现有排序与返回逻辑仍会工作。

## 跨服好友助战

好友列表中的跨服代表卡回退此前已经保证 `unit_id` 存在于接收端 Master Data，但 Live 还会再次读取该卡的引导员/队长技能。v5.07 新增统一的 `live_guest_center_unit()`：

1. 按真实中心卡 → 可识别库存卡的顺序选择代表卡；
2. 验证卡牌存在于接收端 `unit_m`；
3. 验证其 `default_leader_skill_id` 在接收端 `unit_leader_skill_m` 中存在；
4. `/live/partyList` 和 `/live/play` 使用同一个函数。

因此客户端看到的好友助战卡与服务端实际用于计算引导员技能的卡不会漂移。无法安全投影的好友会从助战候选中省略；旧缓存仍提交该用户时，`live/play` 返回签名的 `LIVE_INVALID_PARTY_USER`，不会把无效 Master ID 交给客户端或在计算器中崩溃。

## 未改动范围

本版没有数据库迁移，也没有修改活动剧情、Museum、饰品、好友关系、问候、公告图片或国服数据迁移资源。
