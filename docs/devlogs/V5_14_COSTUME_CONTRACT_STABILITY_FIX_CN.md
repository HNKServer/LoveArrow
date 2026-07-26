# NPPS4 v5.14 服装契约稳定性修复说明

## 本版基线

本版重新以 **v5.12** 为稳定行为基线实现，不沿用上一份 v5.14 中的全衣柜预读和登录性能重构。

`BUILD_ID`：`v5.14-costume-contract-stability-fix`

## 已确认的客户端契约

结合国际服/国服客户端行为与 honoka-chan 的响应结构，本版区分两类数据：

1. `unit/unitAll`、演唱会队伍以及卡牌强化等“持有卡状态”数据：
   - `costume` 只代表真实的 `UserCostumeDress` 换装覆盖；
   - 未换装时完全省略 `costume` 键；
   - 不再把卡牌自身原始外观伪装成一次换装，因此不会产生假的 `SET`/占用。
2. 好友、个人资料、排行榜、助战和问候等“展示中心成员”数据：
   - 没有真实换装时继续使用卡牌原始外观作为展示兜底；
   - 有真实换装时显示换装覆盖；
   - 保持 v5.12 的展示兼容行为。

honoka-chan 的 `unit/all.go` 同样没有在普通持有卡结构中发送 `costume`，而其 profile/friend 中心成员结构要求完整的 `costume` 展示对象。本版按这一差异实现，而不是把所有接口一刀切。

## Lua `null` 崩溃修复

Pydantic 的 `None` 在默认响应序列化中会变成 JSON `null`。KLab Lua JSON 桥会把它暴露为 userdata，随后 `getCostumeAsset` 对其索引并触发 Assert。

本版为所有 Lua 可见的服装模型加入**仅针对 `costume` 字段**的序列化器：

- `costume is None`：删除该键；
- 实际 `CostumeInfo`：正常输出对象；
- 其他值为 `None` 的字段继续保持 v5.12 原有行为，不启用全局 `exclude_none`。

## 占用规则

一条已登记衣装可以永久保存在衣柜中，但同一个 `(unit_id, is_rank_max, is_signed)` 衣装在同一 Profile 下只能同时绑定到一张持有卡。

- 原始卡面不占用衣装；
- 只有 `UserCostumeDress` 记录才表示实际占用；
- 脱下后删除绑定记录，衣装仍保留在衣柜；
- 服务端只在 `dressUp` 操作时查询该衣装是否已由另一张卡使用，不在登录时扫描整个衣柜。

## 内存与数据库策略审计

原版 NPPS4 的主要缓存方式是：

- `BasicSchoolIdolContext.cache`：单次请求范围的字典缓存，请求退出时清空；
- `common.context_cacheable`：复用同一次请求内重复读取的 Master 数据；
- 某些复杂计算器内部的局部字典：对象/操作结束后释放。

原版没有为每个用户长期预载整套持有卡、衣柜或换装表的机制。因此本版：

- 不增加进程级或用户会话级衣柜缓存；
- 不把所有 `UserCostume` 或 `UserCostumeDress` 行预读进内存；
- `appearance_for_owned_unit` 仍按目标 `unit_owning_user_id` 查询对应绑定；
- 沿用 NPPS4 已有的请求级 Master 缓存，不建立第二套缓存架构。

这样会保留 v5.12 原有的登录性能特征，但不会让服务器内存随在线用户数乘以衣柜规模持续增长。

## 未修改部分

- CN/GL 请求级 Profile 识别；
- 共享账号及跨服投影；
- 活动剧情、饰品、好友、排行榜和数据迁移实现；
- v5.12 Android 工作区资源合并与配置权威逻辑；
- Wrapper 搜索栏 Kotlin 修复：`searchInput.text.isNotBlank()`；
- 数据库结构与已有衣柜/换装数据。

本版没有数据库迁移。

## 真机复测顺序

1. CN 登录并关闭公告，确认不闪退；
2. GL 登录并进入换装界面，确认不再出现 `attempt to index a userdata value`；
3. 登记一套衣装但不穿：来源卡和同角色其他卡均不应错误显示 `SET`；
4. 给其中一张卡穿上：只有该卡显示 `SET`，另一张卡选择同一衣装时提示已占用；
5. 脱下后：衣装仍在衣柜，并可重新分配给另一张卡；
6. 测试个人资料、好友助战、排行榜中心成员的原始/换装显示。
