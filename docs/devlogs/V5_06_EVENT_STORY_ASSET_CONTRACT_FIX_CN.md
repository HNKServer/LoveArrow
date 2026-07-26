# NPPS4 v5.06：CN/GL 活动剧情资源契约修复

## 修复范围

本版针对 v5.05 中“活动剧情目录可以列出，但部分条目缩略图空白或点击即触发 Lua `AssetPath` 崩溃”的问题做协议级修复。没有改动活动剧情的用户解锁、已读、完成、奖励防重复状态机，也没有改动饰品、好友、Ranking、Museum、国服公告图片或数据包。

## 真机日志定位

GL 客户端在活动剧情列表中报错：

```text
bad argument #1 to 'sub' (string expected, got userdata)
[C]: in function 'sub'
?: in function 'AssetPath'
?: in function 'update_item'
```

崩溃发生在列表渲染阶段；日志中没有出现后续 `eventscenario/open` 或 `eventscenario/startup` 请求，所以不是剧情播放接口失败，而是 `eventscenario/status` 返回的资源字段不符合 Lua 客户端契约。

## 根因 1：可选资源被序列化成 JSON null

`event_scenario_m.chapter_asset` 本来就是可选字段：

- CN：711 章，其中 546 章为 NULL；
- GL：755 章，其中 595 章为 NULL。

这些 NULL 不是数据库缺损。较新的活动章节会使用客户端通用图标，原版协议在没有专用图标时应当**省略 `chapter_asset` 字段**。

v5.05 将 Python `None` 序列化为 JSON `null`。客户端 JSON/Lua 层把 null 表示为 userdata，随后 `AssetPath` 对它执行 `string.sub`，因此出现“string expected, got userdata”。

v5.06 将 `eventscenario/status` 注册为：

```python
@idol.register("eventscenario", "status", exclude_none=True)
```

NPPS4 的响应序列化器会递归执行 `model_dump(exclude_none=True)`，因此缺少专用章节图标时字段被真正省略，而不是输出 null。

## 根因 2：GL 最后八个活动的 banner ID 并不等于 event ID

LLSIF@Home 的最终 GL 档案证明：

```text
221 -> 215
222 -> 216
223 -> 217
224 -> 218
225 -> 219
226 -> 220
227 -> 221
228 -> 222
```

v5.05 仅在 CN 中处理 `221 -> 215`，GL 对 222–228 仍按原 event ID 请求不存在的 `*_se_ba_t.png`，因此出现空白缩略图。

v5.06 对最终 CN/GL 客户端统一采用上述映射，并保留 CN 特殊活动：

```text
10001 -> 38
```

## 根因 3：返回了未经客户端契约证明的第二 banner 字段

v5.05 额外返回了：

```text
event_scenario_se_btn_asset
```

并构造了不存在的 `*_se_ba_tse.png` 路径。honoka-chan 的 CN schema 和 LLSIF@Home 的最终 GL 响应都没有这个字段。v5.06 已删除该字段，只返回原版可验证的：

```text
event_scenario_btn_asset
```

## 与参考实现的对齐

- honoka-chan：`chapter_asset` 使用 `omitempty`，并证明 CN 的 `10001 -> 38`、`221 -> 215` 映射。
- LLSIF@Home：109 个 GL 活动、755 章；缺少 `chapter_asset` 时省略字段；最终 221–228 banner 映射如上。
- v5.06 投影出的全部 GL 活动 ID、banner 路径以及每章 `chapter_asset` 的“存在/省略和值”，均与 LLSIF@Home 最终档案逐项一致。

## 数据和升级

- 不新增数据库表或 Alembic 迁移；
- 不需要删除账号、活动剧情状态或好友数据；
- 覆盖编译并重启服务端后直接测试；
- 首次测试先不要清客户端全部数据。若某些 GL banner 仍受此前失败下载缓存影响，再仅清下载缓存或触发资源重新下载，不要先清账号数据。

## 版本

```text
Android versionCode: 506
Android versionName: 0.5.6
BUILD_ID: v5.06-event-story-asset-contract-fix
```

## 建议真机回归

1. 进入活动剧情目录并滚动完整列表；
2. 点击此前崩溃的“影之诗 × 学园偶像祭”联动剧情；
3. 点击此前 GL 中为空白的缩略图；
4. 抽查 GL 活动 221–228 对应的最后八组目录；
5. 抽查 CN 特殊映射活动 10001、221；
6. 播放一个此前正常的旧活动剧情，确认没有回归。
