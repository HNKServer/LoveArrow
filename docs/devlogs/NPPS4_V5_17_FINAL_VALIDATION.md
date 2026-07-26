# NPPS4 v5.17 最终验证报告

## 验证结果

- `validate_v517.py`：29 项契约检查全部通过（PC、Android 各一遍）。
- 修改模块 AST 解析：通过。
- 完整 `npps4` Python 树 `compileall`：通过。
- PC 与 Android 内嵌 Python：239 个文件逐字节一致。
- Android 版本：`versionCode 517`、`versionName 0.5.17`。
- `secretbox.py` 的 `common` 启动导入仍存在，未重现 v5.16 的顶层 `NameError`。
- 四个大感谢祭页面 `5K/5L/5M/5N` 的 Java 哈希分别为 1718/1719/1720/1721，均有 CN/GL Profile 和三个按钮。
- 好友资料的中心成员与引导员分别使用独立服装变量。
- 社交服装投影不再读取 `center_unit_owning_user_id` 替换调用者传入的卡。
- 专用饰品制作要求两个不同 owning ID、同一个映射 UR `unit_id`。
- 专用饰品可制作标志要求至少两张合格副本。
- 测试兑换码扩充卡槽到 10000，并为专用目标保留三张合格副本。
- Small Happiness 继续仅向当前 GL 客户端目录开放。
- 两个源码 ZIP 均通过 `unzip -t` 完整性检查。

## 未执行项目

当前环境缺少 PC 运行依赖 `Cryptodome`，因此未在容器中启动完整 NPPS4 进程；但完成了顶层名称/导入静态契约、AST 与编译检查。未执行 Gradle，未生成 APK。

## 真机重点测试

1. GL 账号：UR 露比为引导员、UR 千歌为主唱，只有露比穿 SSR 露比服装。
2. 好友资料：中心成员应始终为千歌及其自身外观；引导员应为露比及其自身服装。
3. 演唱会邀请：助战中心成员应为千歌，服装开关不得把卡牌身份切换成露比。
4. CN 与 GL 招募首页及招募列表：应同时出现 1718–1721 四个大感谢祭页面。
5. 专用饰品：两张相同指定 UR 可制作，制作后第三张可装备。
6. GL Small Happiness 可见；CN 不返回未知 Museum 1698。

## 工作区配置提醒

Android Wrapper 不会覆盖升级前用户已经编辑的 `server_data.json`。旧工作区只有两个大感谢祭页面时，需在配置编辑器中导入本版 `app/src/main/python/npps4/server_data.json`，或清除工作区让它重新初始化。这个行为是为了避免升级时破坏用户自定义卡池和兑换码配置。
