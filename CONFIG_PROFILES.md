# NPPS4 v5.00 CN/GL Profile 配置

## 两个 Profile

- `cn`：国服 9.7.1；
- `gl`：2021 年合并后的 JP/EN/Global。

Profile 由请求特征与登录 Session 决定。`default_profile` 只用于少数登录前无法识别地区的请求。

## 独立下载源

每个 Profile 都有自己的 `enabled`、`backend` 和后端参数：

- `none`：不下发资源，Master DB 必须预先放入本地；
- `n4dlapi`：在线 DLAPI/CDN；
- `internal`：本地 NPPS4-DLAPI archive-root 格式；
- `cn_archive`：国服平铺 ZIP 目录，仅 CN 可用；
- `custom`：自定义 Provider。

推荐 Android 组合：

```toml
[download]
backend = ""
default_profile = "cn"

[download.profiles.cn]
museum_unlock_policy = "all" # normal | all; native catalogue only
enabled = true
backend = "cn_archive"

[download.profiles.cn.cn_archive]
android_archives = "/storage/emulated/0/LoveLive/list_CN_Android/list_CN_Android"
db_root = "data/db_cn_honoka"
application_version = "9.7.1"
client_version = "97.4.6"

[download.profiles.gl]
museum_unlock_policy = "all" # normal | all; native catalogue only
enabled = true
backend = "n4dlapi"

[download.profiles.gl.n4dlapi]
server = "https://ll.sif.moe/npps4_dlapi"
shared_key = ""

[compat]
region = "dual"
cn_wrappers = true
cn_optional_stubs = false
```

也可以分别选择：CN 本地 + GL 本地、CN 本地 + GL 在线、CN 在线 + GL 本地、CN 在线 + GL 在线。某个 Profile 初始化失败不会自动使另一个已就绪 Profile失效；两个都失败时服务端才拒绝启动。

## Wrapper GUI

旧的全局“一键切换国服本地 / 国际服在线”已删除。新界面中：

- CN：禁用 / 本地 / 在线；
- GL：禁用 / 本地 / 在线；
- 默认 CN / 默认 GL：只设置登录前兜底 Profile。

CN 与 GL 不允许同时禁用。

Museum 策略按 Profile 配置：`normal` 只返回该 Profile 已记录的原生解锁项；`all` 返回该 Profile Master DB 中的全部原生目录。默认 CN、GL 均为 `all`，不会把 GL 目录移植到 CN，也不会把 CN 条目写入 GL。
