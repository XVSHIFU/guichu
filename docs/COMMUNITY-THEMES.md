# 社区主题

归处适配版，接入日期：2026-10-03。原作者与归处无隶属关系。

| 主题 | 浅色 / 深色 | 上游 | 许可 |
| --- | --- | --- | --- |
| Catppuccin | Latte / Mocha | https://github.com/catppuccin/palette | MIT |
| Rosé Pine | Dawn / Main | https://github.com/rose-pine/neovim | MIT |
| Everforest | Medium light / dark | https://github.com/sainnhe/everforest | MIT |
| Tokyo Night | Day / Night | https://github.com/folke/tokyonight.nvim | Apache-2.0 |

完整上游许可证随应用发布，位于 `app/public/theme-licenses/`，外观设置的社区分类中也提供访问链接。

## 修改说明

这些是面向归处界面的颜色映射，不是原编辑器主题的完整复制。沿用上游背景、主文字和代表色，映射到页面、卡片、导航、边框与交互状态。共用归处的状态色和深色导航体系。

为保证文字与按钮可读性，Catppuccin 浅色紫改为 #8536eb，并使用白色卡片；Rosé Pine 辅助文字采用 #696580 / #aaa6c1；Everforest 浅色强调色采用 #596b12，深色辅助文字采用 #a0aca3；Tokyo Night 浅色正文、辅助文字、强调色分别采用 #2c4b96、#4c5882、#2358b0。其余角色映射见 theme-init.js。以上修改由归处项目完成。

## 数据来源

- Catppuccin：`catppuccin/palette/main/palette.json`
- Rosé Pine：`rose-pine/neovim/main/lua/rose-pine/palette.lua`
- Everforest：`sainnhe/everforest/master/palette.md`
- Tokyo Night：`folke/tokyonight.nvim/main/extras/lua/tokyonight_day.lua` 与 `tokyonight_night.lua`

## 验证

28 套主题 × 深浅两种模式，检查正文、辅助文字、强调色、按钮和状态色共 560 组对比度，最低要求 4.5:1。浏览器检查社区卡片、转盘循环、首次加载持久化及桌面/手机布局。
