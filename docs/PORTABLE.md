# 便携版与迁移

## 使用便携版

Windows x64：解压整个目录到个人可写文件夹，双击「启动工作台.cmd」。内置 Python 与页面产物，无需安装 Python、Node 或运行构建命令。首次启动会检查本机环境；模型连接需自行填写。

退出服务使用「停止工作台.cmd」。关闭浏览器不代表服务已停止。8765 端口被占用时会报错且不停止其他程序；可运行 `app/Start-Workbench.ps1 -Port 8766`，停止时指定同一端口。

运行失败时查看 `app/data/server-error.log`。解压目录请勿放进系统只读目录。便携版为未签名脚本与运行时发行，尚未做独立干净 Windows 虚拟机验收。

## 完整导出和恢复

1. 等待任务结束，停止工作台。
2. 双击「导出工作台.cmd」，选择一个新的 ZIP 文件保存位置。
3. 在目标工作台停止状态下，双击「恢复工作台.cmd」，选择迁移包并确认。
4. 启动后重新配置模型密钥，检查 MCP 地址/程序并重新授权，刷新本机清单。

包内包含数据库（清单、会话、备注、操作记录）、图标、模型连接信息和 `config-backups` 原始配置备份。模型 API 密钥和 MCP Bearer 凭据从副本中清除，外部 MCP 停用。原始配置备份可能含被管理软件的敏感信息，因此迁移包只适合私人保存，默认授予当前 Windows 用户和 SYSTEM 文件访问权；文件不进行加密。

恢复先校验文件摘要、路径和数据库完整性，再切换数据目录。原数据保存在 `app/data-before-import-...`，不会自动删除。只重新定位本工作台内的配置备份引用；电脑软件的原始路径不改写，跨电脑恢复历史不意味着旧配置可在新电脑执行。活动任务由既有启动恢复逻辑标记中断，不自动重放。

浏览器主题、侧栏偏好和未提交草稿不在迁移包中。数据库简易备份仍使用「备份工作台.cmd」，原恢复脚本只接受本工作区的数据库备份。

脚本方式（自定义端口时两边都指定）：

```powershell
./app/Transfer-Workbench.ps1 -Action export -ArchivePath C:/Backups/guichu.zip -Port 8765
./app/Transfer-Workbench.ps1 -Action import -ArchivePath C:/Backups/guichu.zip -Port 8765
```

## 构建

在 Windows x64 开发环境运行 `python scripts/build_portable.py --name guichu-release-windows-x64`。需要 Node/npm、Python/pip 和网络。输出在 `release/`，该目录不进入 Git。已有输出不会覆盖。

构建只复制明确列出的源码、Agent 资源、前端产物和运行脚本，不打包真实 data、node_modules 或开发缓存。Python 使用官方 3.13.12 embedded x64；依赖固定于 `app/requirements-portable.lock`。包内 build-manifest.json 记录文件摘要与运行时来源，摘要用于完整性核对，不是发布者数字签名。运行时依赖的许可证随包保留。

Python 嵌入式发行说明：https://docs.python.org/3/using/windows.html#the-embeddable-package

## 自动验收

- `python scripts/verify_agent.py`：六项固定运行器/协议场景，输出 JSON 报告；使用模拟模型，不代表模型回答质量评分。
- `python -m unittest discover -s app/tests -p "test_*.py"`：后端检查，使用临时数据库与配置。
- 服务启动后 `npm --prefix app run test:ui:core`：引导、助手、提案、模型目录与主题交互。
- `npm --prefix app run test:ui:all`：扩展浏览器回归。

真实模型质量验收应使用自己的服务：检查一个 MCP、解释一个对象、提出一组分类建议，核对引用来源与提案范围；只对明确需要的修改点击确认。本轮自动回归不消耗真实模型额度。
