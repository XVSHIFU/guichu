# 归处 · Guichu

电脑里的每个工具，都有归处。

归处是面向 Windows 的本机环境工作台，将软件、AI Agent、技能、MCP 和目录串成可搜索、可理解、可管理的清单。

## 功能

- 扫描软件与开发环境，查看来源、安装位置和对象关联。
- 按磁盘浏览目录，按需统计大小，保存分类和备注。
- 接入 OpenAI 兼容模型，使用专用技能进行查询、诊断和变更预览。
- 在聊天中确认受支持的修改，查看备份、冲突与恢复记录。
- 管理本机 stdio 和远程 Streamable HTTP MCP 连接。
- 持久化会话、执行轨迹及长会话摘要，支持28 套深浅主题。

## 启动

需要 Windows、Python 3.12+、Node.js 20+。

```powershell
cd app
python -m pip install -r requirements.txt
npm ci
npm run build
cd ..
.\启动工作台.cmd
```

打开 http://127.0.0.1:8765 ，在「设置 → 模型连接」配置自己的服务。停止服务使用「停止工作台.cmd」，备份使用「备份工作台.cmd」。

清单与会话保存在本机；使用模型时会将请求和相关上下文发送到所配置的服务。配置变更先预览，再由用户确认执行。当前支持范围见 [应用说明](app/README.md)。

## 目录

| 路径 | 内容 |
| --- | --- |
| `app/src/` | React 界面与主题 |
| `app/public/` | 浏览器图标和静态资源 |
| `app/agent/` | 产品指令、技能、上下文和工具 |
| `app/*.py` | 本机服务、采集、模型及操作处理 |
| `app/tests/` | 后端与浏览器测试 |
| `docs/` | 平台与 Agent 实施计划 |
| `PRODUCT.md` / `DESIGN.md` | 产品与设计约定 |
| `local-archive/` | 本机旧版清单和采集资料，不进入仓库 |

运行数据、密钥、备份、构建产物和测试截图均已加入忽略规则。应用源码位于 `app/`，根目录启动脚本会自动定位应用。

## 开发验证

```powershell
cd app
python -m unittest discover -s tests -p "test_*.py"
npm run build
```

[平台计划](docs/PLAN.md) · [Agent 计划](docs/AGENT-PLAN.md)
