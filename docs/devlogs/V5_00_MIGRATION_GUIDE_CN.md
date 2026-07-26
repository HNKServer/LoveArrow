# v4.60 → v5.00 升级说明

## 数据库

不要删除 `data/main.sqlite3`。桌面端启动前运行正常 Alembic 升级；Android Wrapper 会使用内置 Android Schema 路径完成同等迁移。

新增或变化的状态包括：

- `user_client_identity`：同一共享用户的 CN/GL 登录身份；
- `session.profile` 与 `session.server_rsa_label`；
- `random_live_session`；
- 活动剧情与多人剧情解锁状态的 `profile` 维度。

旧 `User.key` 只允许由配置中的历史默认 Profile 认领一次，防止另一客户端家族碰巧使用相同字符串时绑定到错误进度。

## Wrapper 设置迁移

v4.60 的 GUI 使用全局 `download_profile`：

- `cn_archive` 表示整个进程切到国服本地包；
- `gl_online_dlapi` 表示整个进程切到国际服在线源。

v5.00 首次启动时只读取一次该值：

- 原 `cn_archive` → CN 启用/本地，GL 暂时禁用；
- 原 `gl_online_dlapi` → GL 启用/在线，CN 暂时禁用；
- 全新安装 → CN 本地与 GL 在线同时启用。

迁移后旧 `download_profile` 会被删除。之后请在 CN、GL 各自的设置区明确选择“禁用 / 本地 / 在线”。

## config.toml

旧 `[download] backend = ...` 仍可被读取一次以兼容旧配置，但 v5.00 的权威配置是：

```toml
[download]
backend = ""
default_profile = "cn"

[download.profiles.cn]
enabled = true
backend = "cn_archive"

[download.profiles.gl]
enabled = true
backend = "n4dlapi"
```

`[compat] region` 仅作为废弃兼容字段保留，建议写为 `dual`。请求/Session Profile 才是运行时事实来源。

## 已废弃内容

- 旧全局快速切换；
- 进程级 CN/GL 地区选择；
- 强行向国服移植国际服回忆画廊；
- Wrapper 的旧诊断报告入口；
- 默认开启的可选成功 Stub。
