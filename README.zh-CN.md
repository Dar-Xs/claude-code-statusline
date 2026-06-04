# claude-code-statusline

[English](README.md) | **简体中文**

> 一个用于 [Claude Code](https://claude.com/claude-code) 状态栏的「上下文窗口 + 订阅限额」仪表 —— 亚字符级 Unicode 进度条,单文件,零依赖。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python 3.6+](https://img.shields.io/badge/python-3.6%2B-blue.svg)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen.svg)

```
Opus 4.8  ███▍ 42%  413k/1M  │  5h █▛▀▀▀  ²³⁄₄₅ →1h47m · 7d █▙▄▄▄  ⁴¹⁄₆₂ →周四 09:00
```

> 上面这行在文档里是单色的;在你的终端里,进度条是 **绿 → 金 → 红** 渐变。
> <!-- 提示:把这一块换成真实截图,例如 ![screenshot](docs/statusline.png) -->

它在一行里一眼回答两个问题:

1. **模型的上下文窗口满了多少?** —— 赶在自动压缩(auto-compaction)触发之前。
2. **我的订阅配额烧得比时钟快吗?** —— 针对 Pro/Max 套餐。

---

## 显示内容

```
Opus 4.8  ███▍ 42%  413k/1M  │  5h █▛▀▀▀  ²³⁄₄₅ →1h47m · 7d █▙▄▄▄  ⁴¹⁄₆₂ →周四 09:00
└──┬───┘  └─┬─┘ └┬┘ └──┬──┘     └────────┬─────────┘    └────────┬─────────┘
 model   ctx bar  %  tokens/limit   5-hour window            7-day window
```

| 区段 | 含义 |
| --- | --- |
| **`Opus 4.8`** | 当前模型(取自状态栏 payload)。 |
| **`███▍ 42%`** | 上下文窗口填充度。八分块(`▏▎▍▌▋▊▉`)提供约 8× 的亚字符精度。按绝对用量着色:≤25% 绿、50% 金、75% 红 —— 这是刻意提前的预警,因为自动压缩远在硬上限之前就会触发。 |
| **`413k/1M`** | 上下文中的 token 数 / 侦测到的窗口大小。 |
| **`5h …` / `7d …`** | *(仅 Pro/Max)* 两个滚动订阅窗口。每个都是用四分块(`▀▄▙▟`)绘制的**双行堆叠条**:**上行 = 配额已用**,**下行 = 时间已过**。当上层架子超过下层时,说明你花得比时钟快。 |
| **`²³⁄₄₅`** | 上标 = 配额已用百分比,下标 = 窗口已过百分比。 |
| **`→1h47m` / `→周四 09:00`** | 窗口重置时间(5h 用相对时间,7d 用绝对时钟)。 |

限额条按**节奏**(已用 ÷ 已过)着色,而非绝对水平:明显落后于时钟时为绿,超前于时钟时为红。

## 环境要求

- **Python 3.6+** —— 仅标准库,无需 `pip install`。
- **[Claude Code](https://claude.com/claude-code)**。
- 一个**终端**。状态栏是 CLI 特性;它**不会**在 IDE 扩展面板里渲染(VS Code / JetBrains)。
- `5h`/`7d` 条仅在 **Claude.ai Pro/Max** 认证下出现,且要等会话首次 API 响应之后(它们依赖 payload 里的 `rate_limits`)。API-key 认证下会静默省略。

## 安装

1. **下载脚本**到你的 Claude 配置目录:

   ```sh
   curl -fsSL https://raw.githubusercontent.com/Dar-Xs/claude-code-statusline/main/statusline-context.py \
     -o ~/.claude/statusline-context.py
   chmod +x ~/.claude/statusline-context.py
   ```

2. **接线** `~/.claude/settings.json` —— 加上这个顶层键(其余设置保持不变):

   ```json
   {
     "statusLine": {
       "type": "command",
       "command": "python3 ~/.claude/statusline-context.py"
     }
   }
   ```

3. **开一个新会话**(或 `/statusline` 重载)。完成。

> ⚠️ 你的 `~/.claude/settings.json` 里可能含有认证 token。**绝不要提交或分享该文件。** 本仓库只需要独立的 `statusline-context.py`。

## 工作原理

Claude Code 在每次刷新时调用 `statusLine` 命令,把一段 JSON payload 通过 **stdin** 传入。脚本会:

1. 读取 payload,定位会话**记录文件**(`transcript_path`)。
2. 从记录文件末尾倒着扫,找到最近一条带真实 `usage` 块的主链 assistant 回合,累加 `input + cache_creation + cache_read` token —— 这就是实时上下文大小。
3. 若 payload 含 `rate_limits`(Pro/Max),校验并渲染 `5h`/`7d` 窗口。
4. 向 stdout 打印**一行 ANSI 彩色文本**。

它会优雅降级:stdin 格式错误、记录文件缺失、限额数据缺失或乱码,各自回退到一个合理的部分输出,而不是报错。它甚至防御了已知的状态栏 payload bug(例如 `used_percentage` 返回 epoch 值)—— 把任何超出范围的百分比当作「无数据」。

## 自定义

所有旋钮都在文件顶部的 **`── tunables ──`** 区:

| 常量 | 作用 |
| --- | --- |
| `BAR_WIDTH`, `USAGE_BAR_WIDTH` | 上下文条与限额条的宽度(单位:字符格)。 |
| `GRAD_LO` / `GRAD_MID` / `GRAD_HI` | 绿 → 金 → 红 渐变锚点(RGB)。 |
| `CTX_GREEN_AT` / `CTX_RED_AT` | 上下文条达到纯绿 / 纯红的用量断点。 |
| `PACE_RED_RATIO` | 超前时钟多少算「红」(默认 `4/3`)。 |
| `C_TRACK` | 进度条背景「轨道」色。**默认是给浅色终端调的** —— 见下文。 |
| `WEEKDAYS` | 7 天窗口重置日的星期标签。默认简体中文;想要英文就换成 `("Mon", "Tue", …)`。 |

### 深色终端

默认的 `C_TRACK`(`\033[48;5;252m`,浅灰)和渐变锚点是为**浅色**背景调的。在深色终端上,把 `C_TRACK` 调向更深的灰(例如 `238`–`242`),必要时调亮渐变锚点,让填充保持可读。

## 注意事项

- **1M 与 200k 的侦测是启发式的。** stdin payload 不暴露 `[1m]` beta 标志,所以脚本靠推断窗口大小:一次确认的 >200k 读数(或 `exceeds_200k_tokens`)证明是 1M 档;否则 Opus/Sonnet 默认 1M,其余默认 200k。如果你用的是**标准 200k** 的 Opus/Sonnet,在上下文越过 200k 之前,分母(及百分比)会偏低。想硬性覆盖就改 `detect_limit()`。
- **真彩色**在 `COLORTERM` 为 `truecolor`/`24bit` 时启用,否则回退到 256 色立方。少数终端支持真彩却不设该变量。

## 贡献

欢迎 Issue 和 PR —— 它就是一个自带文档的单文件。请保持零依赖、兼容 Python 3.6。

## 许可证

[MIT](LICENSE) © 2026 Dr.Xiong
