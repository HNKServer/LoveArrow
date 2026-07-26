# NPPS4 v5.00 CN/GL 双 Profile 大版本说明

## 基线与边界

本版本从已验证可运行的 v4.60 重新构建。v4.60 中最终确认的数据迁移封面、Honky v4 TEXB、`wv_ba_117.png.imag` 和 `4_0_999.zip` 均逐字节保留。

只定义两种客户端 Profile：

- `cn`：国服 9.7.1 / GHome 客户端；
- `gl`：2021 年合并后的 JP/EN/Global 客户端家族。

不建立单独 JP Profile，也不再把国际服 1360 项回忆画廊移植进国服。国服只保留原生 16 项及其正常全解锁选项。

## 主要变化

- 客户端 Profile 从进程级全局开关改成请求与 Session 级状态；
- 同一个共享账号可保存 CN 与 GL 两组登录身份；
- 用户进度、好友、问候与社交关系继续共享；
- CN/GL Master DB、Release Key 和下载后端按 Profile 隔离；
- CN 与 GL 可分别选择禁用、本地数据或在线 DLAPI；
- 旧 Wrapper 的“国服本地 / 国际服在线”全局一键切换已退出运行；
- Wrapper 中 CN、GL 各自有明确的“禁用 / 本地 / 在线”选择，二者不会互相覆盖；
- 旧 `download_profile` 偏好只在升级时读取一次，迁移完成后删除；
- 默认 Profile 仅用于无法在登录前识别客户端的少量请求，不决定哪个 Profile 可以运行；
- 好友列表、问候、玩家资料、排名与 Live 助战加入跨 Profile Master ID 安全投影；
- 接收端不存在的独占卡牌、技能、饰品、称号和背景不会原样返回；
- GL 开放并复用已在 CN 真机验证的完整饰品生命周期；
- GL 增加 755 项活动剧情和 57 项多人剧情 Provider；
- Random Live 会话持久化并绑定用户与 Profile；
- 新增 `area/list`、`payment/month` 等安全响应；
- 未知 SIF API 返回 HTTP 200 的签名游戏错误，而非网页 404 或虚假成功；
- 删除 Android Wrapper 中已经失去用途的旧诊断报告入口；
- Wrapper 默认监听 `127.0.0.1:8080`。

## 验证边界

已完成 Python 编译、数据库迁移、双 Profile 启动导入、路由注册、GL 饰品生命周期、GL 剧情目录、Android/PC Python 树一致性和 GL APK v1/v2 签名结构验证。

Android Wrapper 源码没有在当前环境中完成 Gradle/Android SDK 的实际 APK 编译；CN↔GL 跨服好友和 GL 饰品仍需两个真实客户端联机验证。GL 测试 APK也尚未完成真机并存安装测试。
