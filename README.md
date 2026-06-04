# claude-code-statusline

**English** | [简体中文](README.zh-CN.md)

> A context-window & subscription rate-limit gauge for the [Claude Code](https://claude.com/claude-code) status line — sub-cell Unicode bars, a single Python file, zero dependencies.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python 3.6+](https://img.shields.io/badge/python-3.6%2B-blue.svg)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen.svg)

```
Opus 4.8  ███▍ 42%  413k/1M  │  5h █▛▀▀▀  ²³⁄₄₅ →1h47m · 7d █▙▄▄▄  ⁴¹⁄₆₂ →周四 09:00
```

> The line above is monochrome here; in your terminal the bars are **green → gold → red**.
> <!-- Tip: replace this block with a real screenshot — e.g. ![screenshot](docs/statusline.png) -->

It answers two questions at a glance, on one line:

1. **How full is the model's context window?** — before auto-compaction bites.
2. **Am I burning my subscription quota faster than the clock?** — for Pro/Max plans.

---

## What it shows

```
Opus 4.8  ███▍ 42%  413k/1M  │  5h █▛▀▀▀  ²³⁄₄₅ →1h47m · 7d █▙▄▄▄  ⁴¹⁄₆₂ →周四 09:00
└──┬───┘  └─┬─┘ └┬┘ └──┬──┘     └────────┬─────────┘    └────────┬─────────┘
 model   ctx bar  %  tokens/limit   5-hour window            7-day window
```

| Segment | Meaning |
| --- | --- |
| **`Opus 4.8`** | Active model (from the status-line payload). |
| **`███▍ 42%`** | Context-window fill. Eighth-blocks (`▏▎▍▌▋▊▉`) give ~8× sub-cell precision. Colored by absolute usage: green ≤ 25%, gold at 50%, red by 75% — an early, actionable warning, since auto-compaction kicks in well before the hard cap. |
| **`413k/1M`** | Tokens in context / detected window size. |
| **`5h …` / `7d …`** | *(Pro/Max only)* The two rolling subscription windows. Each is a **stacked two-row bar** drawn with quadrant blocks (`▀▄▙▟`): **top row = quota used**, **bottom row = time elapsed**. When the top shelf outruns the bottom, you're spending ahead of the clock. |
| **`²³⁄₄₅`** | Superscript = % quota used, subscript = % of the window elapsed. |
| **`→1h47m` / `→周四 09:00`** | When the window resets (relative for 5h, absolute clock for 7d). |

The rate-limit bars are colored by **pace** (used ÷ elapsed), not absolute level: green when comfortably under the clock, red when burning ahead of it.

## Requirements

- **Python 3.6+** — standard library only, nothing to `pip install`.
- **[Claude Code](https://claude.com/claude-code)**.
- A **terminal**. The status line is a CLI feature; it does **not** render in the IDE-extension panels (VS Code / JetBrains).
- The `5h`/`7d` bars appear only for **Claude.ai Pro/Max** auth, and only after the first API response of a session (they rely on `rate_limits` in the payload). With API-key auth they're silently omitted.

## Install

1. **Download the script** into your Claude config directory:

   ```sh
   curl -fsSL https://raw.githubusercontent.com/Dar-Xs/claude-code-statusline/main/statusline-context.py \
     -o ~/.claude/statusline-context.py
   chmod +x ~/.claude/statusline-context.py
   ```

2. **Wire it up** in `~/.claude/settings.json` — add this top-level key (keep your other settings as-is):

   ```json
   {
     "statusLine": {
       "type": "command",
       "command": "python3 ~/.claude/statusline-context.py"
     }
   }
   ```

3. **Start a new session** (or `/statusline` to reload). That's it.

> ⚠️ Your `~/.claude/settings.json` may contain an auth token. **Never commit or share that file.** This repo only needs the standalone `statusline-context.py`.

## How it works

Claude Code calls the `statusLine` command on each refresh, piping a JSON payload to **stdin**. The script:

1. Reads the payload, locates the session **transcript** (`transcript_path`).
2. Scans the transcript from the end for the most recent main-chain assistant turn carrying a real `usage` block, and sums `input + cache_creation + cache_read` tokens — that's the live context size.
3. If the payload includes `rate_limits` (Pro/Max), validates and renders the `5h`/`7d` windows.
4. Prints **one ANSI-colored line** to stdout.

It degrades gracefully: malformed stdin, a missing transcript, or absent/garbled rate-limit data each fall back to a sensible partial line rather than erroring. It even guards against known status-line payload bugs (e.g. `used_percentage` returning an epoch value) by treating any out-of-range percentage as "no data".

## Customization

All knobs live in the **`── tunables ──`** block near the top of the file:

| Constant | What it does |
| --- | --- |
| `BAR_WIDTH`, `USAGE_BAR_WIDTH` | Width (in cells) of the context bar and the rate-limit bars. |
| `GRAD_LO` / `GRAD_MID` / `GRAD_HI` | The green → gold → red gradient anchors (RGB). |
| `CTX_GREEN_AT` / `CTX_RED_AT` | Usage breakpoints where the context bar hits full green / full red. |
| `PACE_RED_RATIO` | How far ahead of the clock counts as "red" (default `4/3`). |
| `C_TRACK` | The bar's background "track" color. **Tuned for a *light* terminal by default** — see below. |
| `WEEKDAYS` | Labels for the 7-day window's reset weekday. Defaults to Simplified Chinese; swap in `("Mon", "Tue", …)` for English. |

### Dark terminals

The default `C_TRACK` (`\033[48;5;252m`, a light grey) and the gradient anchors are tuned for a **light** background. On a dark terminal, lower `C_TRACK` toward a darker grey (e.g. `238`–`242`) and, if needed, brighten the gradient anchors so the fills stay legible.

## Caveats

- **1M vs 200k detection is a heuristic.** The stdin payload doesn't expose the `[1m]` beta flag, so the script infers the window size: a confirmed >200k reading (or `exceeds_200k_tokens`) proves the 1M tier; otherwise Opus/Sonnet default to 1M and everything else to 200k. If you run a **standard 200k** Opus/Sonnet, the denominator (and thus the %) reads low until context crosses 200k. Adjust `detect_limit()` if you want a hard override.
- **Truecolor** is used when `COLORTERM` is `truecolor`/`24bit`, otherwise it falls back to the 256-color cube. A few terminals support truecolor without setting that variable.

## Contributing

Issues and PRs welcome — it's a single self-documenting file. Keep it dependency-free and Python-3.6-compatible.

## License

[MIT](LICENSE) © 2026 Dr.Xiong
