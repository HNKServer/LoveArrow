# NPPS4 v5.08：饰品分组、GL 自动合成与数据联动审计

## 1. 本次日志确认的根因

### 饰品人物分组并不是连续编号

v5.07 通过公式生成饰品页签：

- 虹咲被错误地假定为 `201..213`，并映射到 `list_19..31`；
- Liella! 被错误地假定为 `301..313`，并映射到 `list_36..48`。

但最终客户端使用的是固定的资源目录契约：

- μ’s：`1..9` → `list_1..9`；
- Aqours：`101..109` → `list_10..18`；
- 虹咲：`201..209, 212, 213, 214` → `list_24..35`；
- Liella!：`301..305` → `list_19..23`，`306..309` → `list_36..39`。

这正好解释了真机现象：Liella! 成员串入虹咲、虹咲缺人、两个头像为空，以及客户端请求不存在的 `list_40..47.png.imag` 后在 Liella! 珠宝盒页进入 Lua 空值崩溃。

v5.08 不再根据成员 ID 做算术推导，而是把上述完整表作为 Python 包资源内置，并在加载时校验四个组、成员顺序、资源路径和重复项。Android 不再依赖当前工作目录偶然存在 `assets/serverdata/accessory_tab_list.json`。

## 2. GL 的“自动合成”不是 CN 请求的另一种写法

对所提供 GL 客户端 Lua 5.2 字节码的静态还原确认：

1. `m_accessory/elements/auto_create.lua` 调用 `AccessoryModel.bulkCreate(result.list, ...)`；
2. `bulkCreate` 把每组候选卡牌分别转换成 `unit_owning_user_id`，生成二维数组；
3. 二维数组仍发送到 `/unit/createAccessory` 的 `unit_owning_user_ids`；
4. GL 回调遍历 `response_data.created_accessory`，因此该字段必须是列表；
5. 列表内每个饰品对象还必须带 `reward_box_flag`；
6. CN 回调则读取单个 `created_accessory` 对象和顶层 `reward_box_flag`。

v5.07 只声明 `list[int]`，所以 GL 的 `[[21,22],[26,27]]` 在进入业务 handler 前就被 Pydantic v2 拒绝；即使只放宽请求，旧的单对象响应也仍会让 GL Lua 崩溃。

v5.08 因此按客户端 profile 保持两种协议外形：

- CN：平面卡牌 ID 列表 → 单个饰品对象；
- GL：平面或二维卡牌 ID 列表 → 饰品对象列表，并为每项返回 `reward_box_flag`。

GL 每个内层列表仍调用同一套真实的 NPPS4 饰品生成、抽选、卡牌消耗和金币扣除逻辑。整个 HTTP 请求由同一数据库事务包围；任意后续组失败时，前面组的饰品、卡牌和金币变化都会回滚。跨组重复使用同一卡牌会在业务层明确拒绝。

## 3. CN 页面中的 ID / 迁移密码到底是什么

当前 CN 9.7.1 客户端没有可用的原生 `banner_type=18` SIF2 联动入口，因此此前增加的 WebView 同时暴露了 NPPS4 原本的 SIF1 handover 凭据：

- “生成迁移密码”调用与 `/handover/reserveTransfer` 相同的 SHA-1 规则；
- “导入其他进度”是新增的 SIF1 → SIF1 登录身份迁移界面；
- 它移动的是当前 profile 的客户端登录身份，不会删除同一共享账号的另一 profile 身份。

所以，答案是：**是的，CN WebView 在原本 NPPS4 凭据机制之上补了一个可操作的 SIF1 → SIF1 导入界面。** 它不是把 SIF2 功能改造成了 SIF1 功能，而是同一组 ID/密码可以被两个独立消费者使用。

v5.08 仅把页面文字改清楚：上半部分生成的凭据可以用于另一 SIF1 客户端，也可以在 SIF2/ew 的“游玩数据联动”页填写；下半部分明确标为“导入其他 SIF1 进度”。

## 4. NPPS4 → SIF2/ew 联动当前完成度

所提供 ew 源码与 NPPS4 的核心线路是接通的：

1. SIF2 客户端请求 ew 的 `/user/sif/migrate`；
2. ew 用 SIF1 用户 ID 与联动密码计算与 NPPS4 完全相同的双重 SHA-1；
3. ew 访问配置项 `--npps4` 指向的 `GET /ewexport?sha1=...`；
4. NPPS4 返回等级、相册卡牌（觉醒/签名状态）和称号；
5. ew 当前实际保存并展示的是 SIF1 相册卡牌，同时记录 `sif_user_id` 并发放联动礼物。

因此，**相册联动主链路存在且协议匹配，不会被新增的 SIF1 WebView 导入功能替代或破坏。** 运行 ew 时必须让 `--npps4` 指向该 NPPS4 实例；两端不在同一设备时，默认 `127.0.0.1:51376` 显然不能直接使用。

但不能把它描述成“完整迁移整个 SIF1 账号”：

- ew 源码虽然接收 NPPS4 返回的 `rank` 与 `titles`，当前 `sif_migrate` 实现只消费 `units`；
- 源码仍保留 `TODO - give rewards? Titles?`；
- 这是 SIF2 的**相册/联动资料导入**，不是把 SIF1 等级、货币、卡组、剧情进度等转换成 SIF2 进度；
- 严格的一次性消费和失败重试语义也需要 NPPS4 与 ew 协同设计，不能只在 NPPS4 的 GET 导出端擅自清除密码。

本版本不擅自修改 ew；它修复 NPPS4 饰品问题，并把现有两条迁移/联动用途在 UI 和说明中分开。

## 5. 已执行验证

- 全量 `compileall` 通过；
- 精确饰品页签 guard 通过；
- Pydantic v2：CN 平面请求与 GL 二维请求均通过，空列表、混合层级、空内层均拒绝；
- CN 单对象与 GL 列表响应序列化测试通过；
- GL 批量创建聚合、跨组重复卡牌拒绝测试通过；
- 所提供 CN/GL 客户端字节码契约测试通过；
- NPPS4 `/ewexport` 与 ew `/user/sif/migrate` 路由、URL、双重 SHA-1 和字段消费静态联调通过；
- Android 与 PC 的服务端关键文件保持字节一致。

仍需真机确认：CN/GL 四个饰品页签、GL 单次创建、GL 自动创建一组/多组、创建后的背包刷新，以及 SIF2/ew 指向实际 NPPS4 地址后的相册联动。
