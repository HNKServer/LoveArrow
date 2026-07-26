# NPPS4 v5.29 最终静态与模拟验证

Build ID：`v5.29-special-target-runtime-owned-map-fix`

- 包类型：PC
- Android 版本：`versionCode 529`、`versionName 0.5.29`
- Alembic head：`costume_full_cycle`
- 新数据库迁移：无
- 内嵌 Python 文件：2340

## 本版修复

- `LOVEARROWSHOOT` 的专用饰品目标卡不再只依据当前 Profile 的静态能力目录。
- 合并当前运行时 `accessory_special_m`、当前 Profile 的完整只读映射，以及共享账号已持有专用饰品在 CN/GL 两份服务端内置 Master 中的映射。
- 目标卡属于另一客户端 Profile 时，从对应的服务端内置只读 Unit Master 创建，不依赖同机安装的游戏 APK。
- WebView 兑换码请求从认证 Session 恢复真实 Profile。
- 新建 ORM 卡尚未分配 ID 时仍可纳入三张副本补齐；写入后重新查询玩家数据库验证。
- 兑换结果显示目标总数、验证数、运行时映射数、跨 Profile 映射数及具体未补齐 Unit ID。
- 晚期卡在旧运行时 Unit Master 缺行时，`unit/unitAll` 投影回退到服务端内置的当前 Profile Unit Master。

## 模拟验证

- GL 专用饰品 `516`（`UR Letter from Honoka`）映射到目标卡 `3993`。
- 在当前请求 Profile 为 CN、共享账号持有饰品 `516`、运行时 Master 不含该卡的条件下，能够从 GL 服务端内置 Unit Master 创建并持久化三张 `3993`。
- 将 CN/GL 全部专用饰品映射加入同一共享账号后，解析出 484 个唯一目标 Unit；共创建 1452 张卡，484/484 目标均验证达到三张，缺失列表为空。
- 继承的 v5.24 排名结构回退、Museum 纯相册、内置 Unit Master 和无新迁移检查通过。
- PC/Android 内嵌 Python 树逐字节一致；完整 `compileall` 通过；源码中无 `.pyc` 或 `__pycache__`。

## 未覆盖

当前环境未执行 Android Gradle APK 构建，也不能替代 CN/GL 真机请求与客户端缓存行为验证。真机兑换后应以兑换结果中的 `targets verified` 和 `Warnings` 为准，而不能再仅凭通用成功提示判断补卡是否执行。
