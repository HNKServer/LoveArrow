# NPPS4 v5.14 最终静态验证

- 包：`NPPS4-PC-v5_14-costume-contract-stability-fix-source`
- 通过：**27**
- 失败：**0**
- 基线：v5.12
- 数据库迁移：无
- 真机验证：仍需用户在 CN/GL 客户端执行

| 结果 | 检查项 |
|---|---|
| PASS | all embedded Python files parse |
| PASS | build id is v5.14 stability fix |
| PASS | policy explicitly forbids wardrobe prefetch |
| PASS | native appearance is not returned as an owned-unit override |
| PASS | no binding returns None |
| PASS | invalid binding returns None |
| PASS | actual binding returns CostumeInfo |
| PASS | single-use guard is present only in dressUp path |
| PASS | no costume prefetch state/cache added |
| PASS | appearance query is targeted to one owned card |
| PASS | full owned-unit payload defaults to override-only |
| PASS | unitAll explicitly disables native costume fallback |
| PASS | profile projection explicitly retains display fallback |
| PASS | profile info explicitly retains display fallback |
| PASS | targeted OptionalCostumeModel serializer exists |
| PASS | system/common.py uses targeted costume serializer |
| PASS | system/advanced.py uses targeted costume serializer |
| PASS | system/profile.py uses targeted costume serializer |
| PASS | game/notice.py uses targeted costume serializer |
| PASS | wire format omits absent costume key |
| PASS | wire format preserves real costume object |
| PASS | other v5.12 None fields remain present |
| PASS | route costumeList preserved |
| PASS | route costumeStatus preserved |
| PASS | route dressUp preserved |
| PASS | route makeCostume preserved |
| PASS | no wardrobe removal API invented |

## 额外交叉检查

- PC 与 Android 内嵌 Python 目录：2320 个文件逐字节一致。
- 未加入全衣柜/全换装表预读，也未加入进程级用户缓存。
- 未改动 v5.12 启动、公告、Profile 识别和工作区资源合并流程。
- 验证只覆盖源码结构、Pydantic 实际序列化和静态契约；不能替代真机 Lua/客户端测试。
