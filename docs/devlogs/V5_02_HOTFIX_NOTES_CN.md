> **已由 v5.03 纠正：** 国服 Android 的 `id=12` 实际是不可关闭的强制版本更新 WebView，不是公告入口；v5.02 的重定向只能替换页面内容，不能解除原生阻塞。

# NPPS4 v5.02 CN 启动公告流程纠错热修复

## 本次纠错

v5.01 将国服客户端请求的 `/webview.php/static/index?id=12` 擅自解释成“适龄提示”，并新增了一个原始 NPPS4、honoka-chan、v4.60 和已上传国服客户端资料均不能支持的 `12.html`。这是错误实现。

v5.02：

1. 删除伪造的 `templates/static/12.html`；
2. 不再给 `id=12` 赋予未经证实的页面含义；
3. 将该国服启动前兼容请求以 HTTP 302 导向 `/webview.php/announce/index`；
4. 保持 v4.60 已验证的公告链不变：`/webview.php/announce/index` 再以 HTTP 302 导向 `/main.php/api`；
5. 保留 v5.01 对 `/login/startUp` 中 `config` 漏导入的修复；
6. 不修改国服公告图片、TEXB、`4_0_999.zip`、饰品逻辑或双 Profile 架构；
7. Android 版本更新为 `versionCode 502` / `versionName 0.5.2`；
8. Build ID 更新为 `v5.02-cn-announcement-flow-hotfix`。

## 说明

日志能够证明客户端在 `/login/authkey` 成功后、`/login/startUp` 之前请求了 `id=12`，但不能证明该编号的原始语义。当前修复只把这个异常分支导回用户已经真机验证过的 NPPS4 公告入口，不再凭空制造页面。

服务端测试可以验证完整的 302 跳转链，但无法替代国服客户端对右上角关闭按钮和后续状态机的真机验证。
