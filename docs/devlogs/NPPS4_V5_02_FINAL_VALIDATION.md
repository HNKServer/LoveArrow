> **已由 v5.03 纠正：** 国服 Android 的 `id=12` 实际是不可关闭的强制版本更新 WebView，不是公告入口；v5.02 的重定向只能替换页面内容，不能解除原生阻塞。

# NPPS4 v5.02 CN 启动公告流程纠错验证报告

- Build ID：`v5.02-cn-announcement-flow-hotfix`
- Android：`versionCode 502` / `versionName 0.5.2`
- Android 检查：**37 通过，0 失败**
- PC 检查：**35 通过，0 失败**

## 已确认的根因与误判

上传日志显示，国服客户端在 `/main.php/login/authkey` 返回 200 后创建 `HelpWebView`，随后请求 `/webview.php/static/index?id=12` 并得到 404；这一请求发生在 `/login/startUp` 之前。日志只证明这个请求存在，不能证明它是“适龄提示”。

v4.60 的源码只带有 `templates/static/13.html`，没有 `12.html`；其已验证公告链为：

```text
/webview.php/announce/index
  -> 302 /main.php/api
```

v5.01 新增的“适龄提示”页面属于没有依据的错误实现，v5.02 已删除。

## v5.02 行为

```text
/webview.php/static/index?id=12
  -> 302 /webview.php/announce/index
  -> 302 /main.php/api
```

这不是认定 `id=12` 的含义，而是把该异常启动分支导回已验证的原 NPPS4 公告入口。

## 关键验证

- 伪造的 `12.html` 不存在；
- `id=12` 返回 302，Location 为 `/webview.php/announce/index`；
- 公告入口返回 302，Location 为 `/main.php/api`；
- `id=13` 仍返回 HTML 200；
- 其他未知静态编号仍返回 JSON 404；
- v5.01 的 CN/GL `login/startUp` 运行时身份创建测试继续通过；
- Android/PC Python 树 2314 个文件逐文件一致；
- 两端 `compileall` 通过；
- CN contract guard 通过；
- 最终数据迁移图 SHA-256 保持 `08e658be3c2cc43e4b79a1974da0930da655ea829badef4bafd2a5396c6f4520`；
- `4_0_999.zip` SHA-256 保持 `3d20e352095d450662fc4b736e7156d5ef007c717ffd882adfd4a996f174af2b`；
- `announce.py` 与 v4.60 逐字节相同。

## 仍需真机确认

主机侧无法模拟国服客户端原生 HelpWebView 的关闭按钮及其后续状态机。v5.02 已恢复正确的服务端页面链，但“右上角关闭后是否继续进入 `/login/startUp`”仍需国服客户端实测。
