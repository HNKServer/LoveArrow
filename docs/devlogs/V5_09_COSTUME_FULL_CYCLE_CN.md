# NPPS4 v5.09：服装系统完整生命周期

## 结论与根因

v5.08 以前的修改版 **没有完整实现服装系统**：服务端只有启动批处理中使用的 `costumeList` 空列表，而客户端还会调用 `costumeStatus`、`dressUp` 和 `makeCostume`。

原版 honoka-chan 的问题更直接：它向客户端声明 `costume_status=true`，但同样只实现空的 `costumeList`。客户端点击“登録”（这里指“登记服装”，不是账号登录）后会先锁住弹窗输入；错误回调没有解除锁定，而成功回调只有在读到 `response_data.costume_list` 后才继续播放登记动画并关闭流程。因此缺少 `makeCostume` 或返回形状错误都会表现为音乐仍播放、弹窗却完全点不动。

## v5.09 的精确客户端契约

依据 CN 9.7.1 和 GL 客户端实际 Lua 字节码，四条路由为：

- `costumeList()` → `{costume_list:[...]}`；
- `costumeStatus(status)`；
- `makeCostume(unit_owning_user_id)` → 必须返回 `{costume_list:[新登记项]}`；
- `dressUp(unit_owning_user_id, unit_id, is_rank_max, is_signed)`；移除服装时客户端只发送 `unit_owning_user_id`，其余三个字段被 Lua 的 nil 从 JSON 中省略。

同时修正了两个容易被表面接口检查漏掉的规则：

- 登记状态使用卡牌真实的 `is_rank_max`，不是仅控制显示图面的 `display_rank`；
- 客户端的登记去重键是 `unit_id + is_signed`，不包含 rank，因此服务端唯一约束也与其一致。

## 完成的业务状态

- 持久化登记列表、每张拥有卡牌的当前服装以及全局显示开关；
- 验证卡牌归属、活动状态、当前 CN/GL profile 主数据、稀有度等级门槛；
- 只允许同一成员之间换装；
- 支持客户端真实的“卸下服装”空字段请求；
- `makeCostume` 只返回本次新登记项，重复请求返回空列表，避免客户端本地重复追加；
- `unitAll`、个人资料、好友/问候/排名中心卡与 Live 队伍数据统一携带 `costume`；
- CN/GL 分 profile 保存并在另一 profile 隐藏不存在的地区限定 Master ID；
- 无效换装安全回退到原卡外观，不向客户端发未知 ID。

## 服装专用卡牌

两端客户端把 `disable_rank_up == 5` 定义为 `COSTUME_ONLY_RANK`。这些奖励仍属于 `ADD_TYPE.UNIT`，并在获得时直接加入本地服装列表；它们不是练习伙伴/支援成员。

v5.09 因此同步修正 NPPS4 的通用卡牌分类：

- 类别 5 作为真实拥有卡牌写入 `unit` 表；
- 不再写入 `unit_supporter`；
- `costumeList` 自动发现并持久化用户已拥有的服装专用卡；
- 重启客户端后仍可恢复这些服装；
- 原有升级/觉醒接口继续拒绝对非普通类别执行不适用的养成操作。

## 验证边界

本版可验证“服务端完成了客户端实际使用的服装业务链”，但不能在没有真机复测的情况下宣称动画表现百分之百通过。需要分别在 CN 与 GL 真机复测：登记、重复登记、换装、卸下、显示开关、重启后恢复，以及服装专用卡获得后的自动出现。
