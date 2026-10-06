---
name: inspect-storage
version: guichu-agent-4
description: 检查存储
---

触发：查看目录占用、检查存储。

步骤：先定位授权目录对象。list_directory 仅接受 object_id 和 cursor，首次 cursor=""；每页最多20项。仅在 next_cursor 为非空字符串时保持 object_id，用该游标取下一页；next_cursor=null 表示没有下一页，此时停止续查。任务预算不足也须停止并说明尚未取完。不支持文件名前缀筛选，不传任意路径。

分页复用一次有界枚举，游标120秒有效。目录变化、游标失效或服务重启时丢弃旧页，以 cursor="" 重查；不能把前后两次枚举拼成完整清单，也不能称为原子快照。没有下一页不自动代表枚举完整，还须核对 read_errors=0、enumeration_complete=true，以及所有页均已取得且没有其他截断。read_errors>0 或 enumeration_complete=false 时只能报告观察数量，空数组也不证明目录为空。工具失败或预算不足时明确未取完，不承诺未提供的能力。

目录条目时间用 observed_at；evidence.checked_at 只是目录对象的收录时间。observed_count 是这次当前层枚举的条目数，含目录和链接，不等于普通文件数。measure_directory 返回递归字节数、去重文件数与包含根目录的目录数，口径不同；按问题需要调用，不由名称推算大小。首版不自动删除。

失败边界：目标不明先消歧；工具失败说明实际限制；不得执行技能脚本、扩大授权对象或自行批准修改。

验收：结论引用真实证据；需要变更时只生成待确认提案；执行结果以服务端回执为准。
