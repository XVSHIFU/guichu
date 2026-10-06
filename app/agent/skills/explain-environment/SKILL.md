---
name: explain-environment
version: guichu-agent-4
description: 解释环境对象
---

触发：这个是什么、解释目录或工具用途。

步骤：定位对象，查询来源和直接关联，说明用途、证据与未知；已有依据即结束。

search_objects 和 get_relations 每页最多20项，首次 cursor=""。仅在 next_cursor 为非空字符串时按原查询参数续查；next_cursor=null 表示没有下一页，不代表整个本机已检查。游标无效时从 cursor="" 开始，不混合不同清单或授权范围的分页；仍有截断提示时不能声称结果完整。搜索只匹配清单对象名称/种类，不是目录文件名前缀查询。若改用 list_directory，没有下一页还须检查 read_errors=0、enumeration_complete=true，不能把部分读取后的空结果当作空目录。

Agent 的 process.state 与 coverage 共同解释：not_checked 是没有检查记录；unknown 是信息不足；not_found 仅在 coverage=complete 时表示枚举期间未发现同名进程；matched 只是发现同名线索。partial/failed 时 observed_matches 仅为下限，processCount=null 不能当零；原因与时间引用 reason、observed_at。即使完整枚举也不证明进程身份、此刻运行状态或可以删除。

失败边界：目标不明先消歧；工具失败说明实际限制；不得执行技能脚本、扩大授权对象或自行批准修改。

验收：结论引用真实证据；需要变更时只生成待确认提案；执行结果以服务端回执为准。
