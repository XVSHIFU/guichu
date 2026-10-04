# 归处 · Guichu

**电脑里的每个工具，都有归处。**

归处是面向 Windows 的本机环境工作台，将软件、AI Agent、技能、MCP 和目录串成可搜索、可理解、可管理的清单。

[下载 Windows x64 便携版](https://github.com/XVSHIFU/guichu/releases/latest/download/guichu-release-windows-x64.zip) · [版本说明与校验文件](https://github.com/XVSHIFU/guichu/releases/latest)

## 能做什么

- **了解本机环境**：扫描软件与开发工具，查看来源、安装位置和对象关联。
- **梳理目录**：按磁盘浏览目录，按需统计大小，保存分类与备注。
- **询问归处助手**：接入 OpenAI 兼容模型，查询环境、诊断配置、生成变更预览。
- **确认后再修改**：在聊天中确认受支持的操作，查看执行结果、冲突与恢复记录。
- **管理 MCP 连接**：接入本机 stdio 和远程 Streamable HTTP MCP 服务。
- **保留使用记录**：会话、执行轨迹和长会话摘要持久化保存。
- **选择自己的配色**：28 套主题，各有深浅版本，支持跟随系统与主题转盘切换。

## 快速开始

### 便携版

1. 下载并完整解压 Windows x64 便携包。
2. 双击「启动工作台.cmd」，浏览器打开 [本机工作台](http://127.0.0.1:8765/)。
3. 如需使用助手，进入「设置 → 模型连接」，填写自己的服务地址、模型与密钥。

无需另装 Python 或 Node.js。关闭网页不会停止服务，退出时请运行「停止工作台.cmd」。

![便携版启动](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004091711388.png)

### 从源码启动

需要 Windows、Python 3.12+、Node.js 20+。

```powershell
git clone https://github.com/XVSHIFU/guichu.git
cd guichu/app
python -m pip install -r requirements.txt
npm ci
npm run build
cd ..
.\启动工作台.cmd
```

### 数据与备份

清单与会话保存在本机。使用模型时，请求和相关上下文会发送到你配置的模型服务。

- 「备份工作台.cmd」：备份工作台数据库。
- 「导出工作台.cmd」与「恢复工作台.cmd」：迁移工作台数据，操作前需停止服务；恢复后需重新配置模型密钥。
- 配置变更先预览，再由用户确认执行。具体能力和限制见 [应用说明](app/README.md)。

构建、迁移范围及恢复步骤见 [便携版说明](docs/PORTABLE.md)。

## 功能展示

以下截图来自本机使用，扫描内容与可用操作会随电脑环境而不同。

### 电脑里的工具，都有归处

在工作台集中查看常用工具、环境速览和磁盘空间。

![工作台概览](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004092351170.png)

### 找到工具，也找到它的关联

点击软件或 Agent，先在右侧查看概览，再打开详情了解位置、技能与连接。

![软件与 Agent 列表及侧边概览](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004092453625.png)

![对象详情与关联信息](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004092525505.png)

### 技能与连接，一处查看

查看已发现的技能与 MCP，了解它们的来源、位置和关联宿主。发现配置不代表连接已通过可用性测试。

![技能与连接清单](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004092615850.png)

![技能与连接详情](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004092640347.png)

### 目录占用，看清再处理

按层浏览目录，需要时再统计大小，为整理提供依据。

![目录地图](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004092702244.png)

![目录大小统计](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004092723697.png)

### 直接问你的环境

选择一个工具作为上下文，让助手解释它的位置、关联和配置情况。

![归处助手回答环境问题](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004093043609.png)

<details>
<summary>查看模型连接设置</summary>

支持添加 OpenAI 兼容服务，管理模型目录、测试连接，并设置调用预算。

![模型提供商列表](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004091851156.png)

![模型连接配置](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004091911398.png)

</details>

### 每一步，都能回看

助手过程展示参考了 DeepSeek Harness 的交互方式。可以展开实际工具调用，查看读取结果与执行轨迹；最终回答独立呈现。

![助手执行过程](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004092124235.png)

![助手轨迹与工具记录](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004093201012.png)

![展开查看处理过程](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004093323985.png)

### 先看修改，再决定执行

受支持的修改会生成提案，展示目标、前后差异和备份位置。用户可以确认执行，也可以拒绝。

下图是 **待确认的停用预览**，并不表示 MCP 已被停用。实际结果以操作记录为准。

![MCP 停用提案，等待用户确认](https://raw.githubusercontent.com/XVSHIFU/Picture-bed/img/image-20261004093423784.png)

## 项目结构

| 路径 | 内容 |
| --- | --- |
| `app/src/` | React 界面与主题 |
| `app/public/` | 浏览器图标和静态资源 |
| `app/agent/` | 产品指令、技能、上下文和工具 |
| `app/*.py` | 本机服务、采集、模型及操作处理 |
| `app/tests/` | 后端与浏览器测试 |
| `scripts/` | 便携版构建与固定场景验收 |
| `docs/` | 使用说明与实施计划 |
| `PRODUCT.md` / `DESIGN.md` | 产品与设计约定 |

应用源码位于 `app/`，根目录启动脚本会自动定位应用。运行数据、密钥、备份、构建产物和测试截图均已加入 Git 忽略规则；本机旧清单归档 `local-archive/` 不进入仓库。

## 开发验证

在仓库根目录运行：

```powershell
# 后端测试
python -m unittest discover -s app/tests -p "test_*.py"

# Agent 固定场景验收，不调用真实模型服务
python scripts/verify_agent.py

# 前端构建
npm --prefix app run build
```

工作台启动后，可运行核心浏览器回归：

```powershell
npm --prefix app run test:ui:core
```

[平台计划](docs/PLAN.md) · [Agent 计划](docs/AGENT-PLAN.md) · [便携版与迁移](docs/PORTABLE.md) · [社区主题来源](docs/COMMUNITY-THEMES.md)

## 社区

[LINUX DO](https://linux.do/) · 开发者交流社区。

## 许可证

MIT。第三方依赖、图标、字体与社区主题遵循各自的许可证。
