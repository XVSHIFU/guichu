---
name: manage-capability
version: guichu-agent-1
description: 管理已支持能力
---

触发：停用或启用当前MCP、修改保留决定。

步骤：先get_action_capabilities，再读取对象；仅propose_change生成差异；等待卡片确认，不自行执行。Codex 用户 MCP 支持 mcp_enabled。Claude Code 用户 MCP 仅支持 claude_mcp_remove（enabled=false），含义是移除注册并备份，不是启用开关；必须向用户明确这一差别。恢复通过 propose_restore 使用同会话提案 ID。

失败边界：目标不明先消歧；工具失败说明实际限制；不得执行技能脚本、扩大授权对象或自行批准修改。

验收：结论引用真实证据；需要变更时只生成待确认提案；执行结果以服务端回执为准。
