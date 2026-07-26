# NPPS4 v5.03 最终验证报告

- Build ID：`v5.03-cn-profile-version-gate-fix`
- Android：`versionCode 503` / `versionName 0.5.3`
- Android 专项检查：**43 通过，0 失败**
- PC 专项检查：**41 通过，0 失败**

## 日志结论

当前日志中的 `id=12` 页面并非普通公告，而是国服 Android 客户端的强制版本更新 WebView。三个 HTTP 跳转均成功完成并最终取得 `/main.php/api` 的 200 响应，但客户端始终没有发出 `/login/startUp`，说明阻塞来自原生不可关闭的版本更新状态，而不是网页连接失败。

## 已确认根因

v5.00 将 `Client-Version: 9.7.1` 错当成内容版本并判为 GL，使国服 `/login/authkey` 响应使用 GL `Server-Version: 59.4`。国服客户端由此检测到版本不匹配并进入 Android `VERSION_UP_WEBVIEW_URL`（`id=12`）。v5.02 的重定向仅替换了弹窗里的网页，没有改变弹窗原生的无按钮状态。

## 修复验证

- 9.7/9.11 这类应用版本不再触发 GL 猜测；
- 97.x/59.x 内容版本回退识别仍保留；
- 国服 APK 内嵌公钥与 `honoka_server_key.pem` 一致；
- honoka RSA key 在 token 创建前解析为 CN；
- NPPS4 default RSA key 在 token 创建前解析为 GL；
- 已签名 Session 的 Profile 覆盖后续歧义 Header；
- CN 响应显式返回 `Server-Version: 97.4.6`；
- GL 响应显式返回 `Server-Version: 59.4`；
- release keys 与 CN 专用 Header 均显式按请求 Profile 选择；
- `id=12` 返回普通 404，不再跳到公告；
- 真正公告仍保持 `/announce/index → /main.php/api`；
- Android/PC Python 树一致；
- 全量 `compileall` 与 CN contract guard 通过。

## 资源未变

```text
4_0_999.zip
SHA-256 3d20e352095d450662fc4b736e7156d5ef007c717ffd882adfd4a996f174af2b

npps4_data_transfer.png
SHA-256 08e658be3c2cc43e4b79a1974da0930da655ea829badef4bafd2a5396c6f4520
```

## 真机验收点

正常启动时日志中应当：

1. `/main.php/login/authkey` 返回 200；
2. **不再请求** `/webview.php/static/index?id=12`；
3. 新账号继续请求 `/main.php/login/startUp`，旧账号继续正常登录；
4. 真正公告通过 `/webview.php/announce/index` 打开并显示原生关闭按钮；
5. 关闭后进入游戏。
