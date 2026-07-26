# NPPS4 v5.18：国服贴纸商店中文与耐力恢复道具

## 基线

本版直接继承 v5.17，保留：

- 好友资料与演唱会中“主唱”和“引导员”的卡牌、属性及服装严格分离；
- CN/GL 独有卡与助战安全回退；
- 四个大感谢祭签名招募页面；
- 专用饰品消耗两张相同指定 UR，测试兑换码保留第三张用于装备；
- `secretbox.py` 的 Android 启动导入修复；
- Small Happiness 仅在拥有 Museum 1698 的 GL 客户端显示。

## 国服贴纸商店名称

### 默认配置

`StickerShop` 新增可选字段 `name_cn`。随包 `server_data.json` 已从现有国服目录反向写入名称：

- 称号：570 个有可用的国服目录名称；
- 背景：224 个有可用的国服/honoka 目录名称；
- 贴纸兑换点：9 个；
- Item 5：官方名称“辅助招募券”。

849 行商店配置中共有 804 行写入 `name_cn`；按 `(add_type, item_id)` 去重后，紧凑名称目录包含 799 个对象。其中 788 行包含中文，剩余 16 行是 `PERFECT WORLD`、`WHITE ISLAND` 等本来就以拉丁字母作为主体的活动专名。

名称先采用现有国服 Master/honoka 数据中的中文字段；对于 Master 仍留着英文、但日文原名和既有国服译名规则足以确定的批量条目（例如“情人节礼物 2021/2022”、全国大会名次、WORLD 形象女孩），本版使用可审计的确定性映射反向补全。无法可靠确定的活动专名不做机器翻译。

### 已存在的旧工作区

Android Wrapper 按设计不会覆盖用户已有的 `server_data.json`。因此本版另带：

```text
npps4/assets/cn_sticker_shop_names.json
```

旧配置缺少 `name_cn` 时，`exchange/itemInfo` 会在该次请求内读取这份约 38 KiB 的名称表；自定义且目录中不存在的商品再按 ID 批量查询活动中的 CN Master。

两层结果都只保存在 `BasicSchoolIdolContext.cache`，请求完成即释放。没有按用户、Session 或进程常驻预读整个商店，也没有加载玩家库存。

商品是否发送仍由 v5.16 的实际客户端目录过滤决定，中文补全不会把 CN 不认识的 GL 商品重新放回列表。

## 耐力恢复道具

### 国服

honoka-chan 的默认耐力道具清单共有 52 个 ID，但它的合并 `main.db` 没有 `recovery_item_m`，所以旧版 NPPS4 生成的 CN `item.db_` 中该表为空。

本版加入经过客户端数据核对的：

```text
npps4/assets/cn_recovery_items.json
```

它保存 52 行完整 Master 数据，包括：

- 道具 ID；
- 国服名称与说明；
- 固定值/百分比恢复类型；
- 恢复量；
- 小/中/大图资源路径；
- release tag。

CN Split Master 生成器版本提升为：

```text
cn_honoka_master:v7_recovery_items
```

因此已有旧缓存会重新生成。实际生成的 `item.db_` 中 `recovery_item_m` 为 52 行，而不是只在 API 中硬编码图标。

### 国际服

提供的 GL 客户端 Master 自带 47 行耐力恢复道具，全部由原有 GL Master 路径使用。CN 比 GL 多出的 801–805（汉堡、牛奶瓶、月饼、Liella! 巧克力、粽子）不在该 GL 客户端 Master 中，因此不会强行把未知 ID 发送给 GL。

统一账户的玩家库存表仍然共享，但 `lp_recovery_item` 返回前会按当前 Profile 的活动 `recovery_item_m` ID 集合过滤：

- CN 可见并可使用 52 种；
- 当前提供的 GL 客户端可见并可使用 47 种；
- 先在 CN 领取的 CN 独有道具不会污染 GL 返回；
- `common/recoveryEnergy` 继续按 Master 中的 `recovery_type` 和 `recovery_value` 正常消耗与恢复。

能力 ID 集合使用 NPPS4 原有的单请求缓存，请求结束释放。

## LOVEARROWSHOOT

重新输入测试兑换码后：

- 当前客户端 Master 支持的每一种耐力恢复道具补到 9999；
- Item 1 普通招募券继续补到 9999；
- Item 5 辅助招募券明确补到 9999；
- 当前招募页面实际使用的其他招募券也继续补到 9999；
- Item 2/3/4 仍按 NPPS4 既有语义分别映射友情点、金币和爱心，并由货币字段补足；
- 所有补充均为幂等“补到目标值”，不会每次无限叠加。

升级本身不会自动替用户兑换；需要在 CN 和 GL 各进入一次并重新输入 `LOVEARROWSHOOT`，才能分别补齐各 Profile 客户端支持的目录。

## 数据库与兼容性

- 不需要玩家数据库迁移；
- 不修改现有恢复道具持有记录；
- 不长期缓存玩家数据；
- 不把 CN 独有恢复道具伪装成 GL 道具；
- 不改变 v5.17 的卡牌、服装、好友、饰品与招募语义。
