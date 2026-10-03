---
name: organize-inventory
version: guichu-agent-1
description: 整理清单
---

触发：整理清单、给对象分类。

步骤：检索和消歧，说明分类依据；软件可用 batch_category 提案进行原子批量分类：先查询 get_action_capabilities 获得合法分类；parameters.changes 是 object_id/category 列表（1–50 项），提案 object_id 必须是首项 ID，其余参数填 null。只纳入已授权的软件，分类为 null 表示清除手动分类。说明每项依据并等待确认；不能给技能或目录套软件分类。

失败边界：目标不明先消歧；工具失败说明实际限制；不得执行技能脚本、扩大授权对象或自行批准修改。

验收：结论引用真实证据；需要变更时只生成待确认提案；执行结果以服务端回执为准。
