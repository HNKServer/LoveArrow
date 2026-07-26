# NPPS4 v5.08 最终验证报告

Build ID：`v5.08-accessory-tab-gl-auto-create`  
Android：`versionCode 508` / `versionName 0.5.8`

自动验证共 **61 项通过、0 项失败**。本报告覆盖源码契约和隔离动态测试；最终客户端真机回归仍然必须执行。

## 修复结论

- 饰品人物页签改为与所提供 honoka-chan 完全一致的固定资源映射，不再用连续编号推导。
- 虹咲恢复 12 人：`201..209, 212, 213, 214`；Liella! 恢复 9 人：`301..309`。
- 不再向客户端发布不存在的 `list_40` 及以上资源。
- GL `createAccessory` 同时支持平面列表和自动创建使用的二维列表；响应保持 GL 列表形态并为每项提供 `reward_box_flag`。
- CN 仍保持单对象响应，未被 GL 协议外形污染。
- CN WebView 文字已明确区分 SIF1→SIF1 身份迁移与 SIF2/ew 相册联动。

## 自动验证分类

| 分类 | 通过 | 失败 |
|---|---:|---:|
| 此前修复回归保护 | 11 | 0 |
| 饰品页签契约 | 21 | 0 |
| CN/GL createAccessory | 13 | 0 |
| 迁移与 SIF2/ew 联动 | 8 | 0 |
| 构建与源码一致性 | 8 | 0 |

完整逐项结果见同目录 `NPPS4_V5_08_FINAL_VALIDATION.json`。

## 补充客户端证据

- 所提供 GL Lua 5.2 字节码显示 `bulkCreate` 发送二维 `unit_owning_user_ids`，并遍历 `response_data.created_accessory`。
- 所提供 CN 字节码读取单个 `response_data.created_accessory` 和顶层 `reward_box_flag`。
- Logcat 中 v5.07 对 `[27,22]` 和 `[[21,22],[26,27]]` 均在 Pydantic 层报错，尚未进入业务逻辑。
- Logcat 中错误页签映射触发了 `list_40.png.imag` 至 `list_47.png.imag` 的 404。

## SIF2/ew 边界

NPPS4 `/ewexport` 与 ew `/user/sif/migrate` 的 URL 和双重 SHA-1 规则一致。ew 当前会导入 SIF1 相册卡牌、记录 `sif_user_id` 并发放联动礼物；所提供 ew 源码仍未消费 NPPS4 返回的 `rank` 与 `titles`，并保留 `TODO - give rewards? Titles?`。因此这是相册联动，不是完整 SIF1 账号转换。

## 真机复测清单

1. CN 与 GL 分别打开专用饰品和珠宝盒四个团体页签，核对虹咲 12 人、Liella! 9 人及头像。
2. GL 单组创建饰品。
3. GL 自动创建一组和多组，并确认卡牌/金币扣除、背包刷新和礼物箱标志。
4. CN 创建、强化、重制、出售回归，确认协议外形未被 GL 分支影响。
5. 让 ew 的 `--npps4` 指向可达的 NPPS4 地址，执行一次 SIF2 相册联动。
