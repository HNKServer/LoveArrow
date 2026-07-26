# NPPS4 v5.03 — CN 强制更新 WebView / Profile 版本域修复

## 这次日志已经把问题钉死

`CONNECTING` 并不是 `/main.php/api` 没有加载成功。`sif_cn_full_log40.txt` 中实际请求链是：

```text
POST /main.php/login/authkey                         200
GET  /webview.php/static/index?id=12                302
GET  /webview.php/announce/index                    302
GET  /main.php/api                                  200
```

随后客户端没有再请求 `/main.php/login/startUp`，而 `HelpWebView` 一直留在屏幕上。

对国服 9.7.1 客户端资源的复核确认：

- Android 的 `VERSION_UP_WEBVIEW_URL` 是 `/webview.php/static/index?id=12`；
- iOS 对应 `id=11`；
- 版本更新弹窗使用原生不可关闭配置（无关闭按钮）；
- 真正的启动公告使用 `login_news_uri`，是另一条可关闭的 WebView 流程。

因此 v5.02 把 `id=12` 重定向到公告，只是把 **API 文档画进了“必须更新”的原生弹窗里**。页面内容看起来对了，但弹窗类型没有改变，当然仍然没有叉号，也不可能进入游戏。

## 根因

v5.00 的双 Profile 检测把 `Client-Version: 9.7.1` 当成内容版本，并按“主版本小于 90”误判成 GL：

```text
CN APK/application version: 9.7.1
CN content/server version:   97.4.6
GL content/server version:   59.4
```

`9.7.1` 是应用版本，不是 `97.4.6`/`59.4` 这一层的内容版本。误判后，`/login/authkey` 的响应继承 GL Profile，并向国服客户端返回 GL 的 `Server-Version: 59.4`。国服客户端检测到本地 CN 内容版本与远端版本不一致，于是进入 `id=12` 的强制更新弹窗。

另外，所提供国服 APK 的 `classes.dex` 中确实嵌入了 `honoka_server_key.pem` 对应的公钥，而不是 NPPS4/GL 默认公钥。因此 RSA 密钥域可以作为登录阶段的可靠 CN/GL 判据。

## v5.03 的修复

1. `9.x Client-Version` 不再被猜成 GL；它被视为登录前的歧义应用版本。
2. `/login/authkey` 解密 `dummy_token` 后，根据实际匹配的 RSA 公钥指纹确定 Profile：
   - honoka key → CN；
   - NPPS4 default key → GL；
   - 自定义未知 key → 不猜，保留显式 Header/默认 Profile。
3. Profile 在创建登录 Session **之前**完成切换，因此 token 从一开始就记录正确的 CN/GL 身份。
4. 后续认证请求以已签名 Session 中保存的 Profile 为权威，不再因为同一个 `9.x` Header 被重新误判。
5. `Server-Version`、`release_info` 和 CN 专用响应头都显式使用 `context.profile`，不再依赖可能残留的 ContextVar。
6. 删除 v5.02 的 `id=12 → 公告` 特判。`id=12` 恢复为普通缺失静态页；正常流程修好后客户端根本不应请求它。
7. 保留真正的启动公告链：

```text
/webview.php/announce/index → /main.php/api
```

## 未修改

- 不修改国服 APK；
- 不修改数据库 Schema 或现有账号数据；
- 不修改 CN 数据包、`4_0_999.zip`、公告图片、招募、Museum、饰品实现；
- 不重新引入 116/117 更新层；
- 不改变 CN/GL 独立下载源和共享用户/社交数据的阶段架构。

无需清除游戏数据或服务端数据库。编译安装新的 Wrapper 后，彻底结束国服客户端并重新启动即可。

## 验证

- Android 专项检查：43 通过，0 失败；
- PC 专项检查：41 通过，0 失败；
- Android/PC Python 树逐文件一致：2314 个文件；
- Python `compileall`：通过；
- CN contract guard：通过；
- 国服 APK 内嵌 honoka/CN 公钥：通过；
- CN authkey 在 token 创建前切换为 CN：通过；
- GL authkey 在 token 创建前切换为 GL：通过；
- CN 响应 `Server-Version=97.4.6`：通过；
- GL 响应 `Server-Version=59.4`：通过；
- `id=12` 不再伪装成公告：通过；
- `id=13` 原静态页仍可用：通过；
- `4_0_999.zip` 与最终数据迁移图 SHA-256 保持不变。

当前环境没有完整 Android SDK/Gradle Wrapper，因此没有声称已完成 APK 构建或真机验证。最终仍需在国服客户端确认：本次启动不再访问 `id=12`，而是继续进入 `/login/startUp` 或正常登录，然后出现真正可关闭的公告。
