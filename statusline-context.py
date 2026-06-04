#!/usr/bin/env python3
"""Claude Code statusLine: context-window usage gauge + subscription rate limits.

Reads the statusLine JSON payload from stdin, locates the session
transcript, and computes how full the model's context window is by
inspecting the most recent main-chain assistant turn. When the payload
carries Claude.ai subscription usage (`rate_limits`, present only for
Pro/Max after the first API response), each of the 5-hour and 7-day
windows is drawn as a stacked two-row bar (quadrant blocks) — top row =
quota used, bottom row = time elapsed in the window — beside a `used ⁄ time`
figure, so 'am I burning faster than the clock?' reads at a glance.

Output (single line, ANSI-colored). The context gauge uses sub-cell eighth
blocks (▏▎▍▌▋▊▉); the rate-limit bars stack two rows with quadrant blocks
(▀▄█) in the same visual family. All three are 8 cells over a solid grey track:
    Opus 4.8  ███▍ 42%  413k/1M  │  5h █▛▀▀▀  ²³⁄₄₅ →1h47m · 7d █▙▄▄▄  ⁴¹⁄₆₂ →周四 09:00
"""
import json
import math
import os
import sys
import time
from datetime import datetime

# ── tunables ────────────────────────────────────────────────────────────
BAR_WIDTH = 8           # context bar: cells (sub-cell eighths give 8x finer)
USAGE_BAR_WIDTH = 8     # rate-limit bars: same width as the context bar
FILL = "█"              # fully filled cell
EMPTY = " "             # empty cell — the C_TRACK background *is* the track
# Left-aligned partial blocks for sub-character precision. Index = eighths
# filled in the boundary cell: 1=1/8 .. 2=1/4 .. 4=1/2 .. 6=3/4 .. 7=7/8.
PARTIALS = ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉")

# Quadrant blocks give a 2-col × 2-row cell in the SAME solid family as █, so a
# stacked bar stays visually unified with the context gauge. Indexed by quadrant
# bits TL=1 TR=2 BL=4 BR=8: top row carries quota used, bottom row time elapsed.
QUAD = (" ", "▘", "▝", "▀", "▖", "▌", "▞", "▛",
        "▗", "▚", "▐", "▜", "▄", "▙", "▟", "█")

# Small raised / lowered digits for the stacked "used ⁄ time" figure.
SUP_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
SUB_DIGITS = "₀₁₂₃₄₅₆₇₈₉"

# Weekday labels for the 7-day window's absolute reset time (e.g. "周四 09:00").
# Defaults to Simplified Chinese — replace with your own locale if you prefer:
#   WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# Greys for non-bar chrome. Bar fills use the green→gold→red gradient below.
C_DIM = "\033[38;5;250m"   # separators
C_MUTE = "\033[38;5;244m"  # token text / reset text
C_RESET = "\033[0m"

# Gradient anchors (RGB), dark & saturated so they read on a LIGHT terminal and
# on the grey track: green → gold-yellow → red. Quantized to 256 they land on
# the old 34 / 178 / 160, so the look is continuous with what came before.
GRAD_LO = (0, 175, 0)
GRAD_MID = (215, 175, 0)
GRAD_HI = (215, 0, 0)
# Truecolor renders a smooth ramp; without it we fall back to the 256 cube.
TRUECOLOR = os.environ.get("COLORTERM", "").lower() in ("truecolor", "24bit")
# Bar track BACKGROUND. Painted behind the whole bar so the unfilled half of a
# partial cell (▎▌▊…) reads grey instead of the terminal's default background.
# Tuned for a LIGHT terminal: raise toward 255 for a fainter groove, lower
# toward 245 for a darker one.
C_TRACK = "\033[48;5;252m"

# Context bar colour ramps green→gold→red across these usage breakpoints
# (gold at the 0.50 midpoint). Auto-compact bites well before the hard cap, so
# red arriving by 3/4 full is a deliberately early, actionable warning.
CTX_GREEN_AT = 0.25
CTX_RED_AT = 0.75
# Rate-limit bar colour ramps by *pace* = used / time-elapsed: 3/4 green, 1 gold,
# 4/3 red — symmetric around on-pace (ratio 1) in log space.
PACE_RED_RATIO = 4 / 3

# Window durations (seconds), used only to sanity-bound resets_at.
WIN_5H = 5 * 3600
WIN_7D = 7 * 86400


def fmt_tokens(n: int) -> str:
    """12345 -> '12.3k', 123456 -> '123k', 1000000 -> '1M'."""
    if n >= 1_000_000:
        s = f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{s}M"
    if n >= 100_000:
        k = round(n / 1000)               # 999_999 rounds to 1000k -> show 1M
        return "1M" if k >= 1000 else f"{k}k"
    if n >= 1000:
        return f"{n / 1000:.1f}k"
    return str(n)


def fmt_duration(secs: float) -> str:
    """Seconds-until -> compact human span: '3d4h' / '2h13m' / '47m' / 'now'."""
    secs = int(secs)
    if secs <= 0:
        return "now"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins, _ = divmod(rem, 60)
    if days:
        return f"{days}d{hours}h"
    if hours:
        return f"{hours}h{mins}m"
    return f"{mins}m"


def fmt_reset_clock(epoch: float, now: float) -> str:
    """Absolute reset time, scaled to how far away it is.

    today -> 'HH:MM'; within a week -> '周四 HH:MM'; further -> 'MM-DD HH:MM'.
    Uses local timezone (datetime.fromtimestamp without tz).
    """
    dt = datetime.fromtimestamp(epoch)
    hm = dt.strftime("%H:%M")
    days_ahead = (dt.date() - datetime.fromtimestamp(now).date()).days
    if days_ahead <= 0:
        return hm
    if days_ahead <= 6:
        return f"{WEEKDAYS[dt.weekday()]} {hm}"
    return dt.strftime("%m-%d ") + hm


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _rgb256(r, g, b):
    """Nearest 6×6×6-cube index, for terminals without truecolor."""
    def q(v):
        return 0 if v < 48 else 1 if v < 115 else (v - 35) // 40
    return 16 + 36 * q(r) + 6 * q(g) + q(b)


def gradient_fg(t: float) -> str:
    """Foreground SGR for position `t` (0..1) on the green→gold→red ramp."""
    t = max(0.0, min(1.0, t))
    if t <= 0.5:
        r, g, b = _lerp(GRAD_LO, GRAD_MID, t * 2)
    else:
        r, g, b = _lerp(GRAD_MID, GRAD_HI, (t - 0.5) * 2)
    if TRUECOLOR:
        return f"\033[38;2;{r};{g};{b}m"
    return f"\033[38;5;{_rgb256(r, g, b)}m"


def context_color(frac: float) -> str:
    """Absolute-usage colour: 1/4 green, 1/2 gold, 3/4 red, gradient between."""
    return gradient_fg((frac - CTX_GREEN_AT) / (CTX_RED_AT - CTX_GREEN_AT))


def pace_color(usage_frac: float, time_frac: float) -> str:
    """Pace colour from used/elapsed: 3/4 green, 1 gold, 4/3 red (log-symmetric)."""
    if time_frac <= 0:
        t = 1.0 if usage_frac > 1e-6 else 0.0
    elif usage_frac <= 0:
        t = 0.0
    else:
        t = 0.5 + math.log(usage_frac / time_frac) / (2 * math.log(PACE_RED_RATIO))
    return gradient_fg(t)


def detect_limit(model_id: str, ctx: int, exceeds_200k: bool) -> int:
    """Best-effort context-window size.

    statusLine stdin does not expose the `[1m]` beta flag, so we infer:
    a confirmed >200k reading proves the 1M tier; otherwise opus/sonnet
    (the 1M-capable families) default to 1M, everything else to 200k.
    """
    if exceeds_200k or ctx > 200_000:
        return 1_000_000
    mid = (model_id or "").lower()
    if "opus" in mid or "sonnet" in mid:
        return 1_000_000
    return 200_000


def _tail_lines(path: str, block_size: int = 65536):
    """Yield a file's lines from last to first without loading it all.

    A transcript can grow to many MB and the status line refreshes often, so
    reading the whole file each time is O(file size). We usually need only the
    last turn, so seek to the end and walk backwards a block at a time, holding
    each block's (possibly truncated) leading fragment until the preceding
    block completes it.
    """
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        pos = fh.tell()
        fragment = b""
        while pos > 0:
            read = min(block_size, pos)
            pos -= read
            fh.seek(pos)
            chunk = fh.read(read) + fragment
            pieces = chunk.split(b"\n")
            fragment = pieces[0]            # may continue into the next block back
            for piece in reversed(pieces[1:]):
                yield piece.decode("utf-8", "replace")
        if fragment:
            yield fragment.decode("utf-8", "replace")


def last_context_tokens(transcript_path: str) -> int:
    """Tokens occupying the context at the most recent main-chain turn.

    Scans the JSONL transcript from the end and returns the first
    assistant message that carries a real `usage` block and is not a
    sub-agent sidechain. Context size = input + cache_creation + cache_read.
    """
    try:
        for line in _tail_lines(transcript_path):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("type") != "assistant" or rec.get("isSidechain"):
                continue
            usage = (rec.get("message") or {}).get("usage")
            if not usage:
                continue
            return (
                usage.get("input_tokens", 0)
                + usage.get("cache_creation_input_tokens", 0)
                + usage.get("cache_read_input_tokens", 0)
            )
    except OSError:
        return 0
    return 0


def render_bar(frac: float, width: int) -> str:
    """A sub-character-precision bar `width` cells wide.

    Effective resolution is `width * 8`: the boundary cell is drawn with a
    left-aligned eighth block (▏▎▍▌▋▊▉), so the default 8-cell bar resolves
    ~1.5%. Colored green→gold→red by absolute usage (see `context_color`).
    """
    frac = min(1.0, max(0.0, frac))
    color = context_color(frac)
    eighths = int(round(frac * width * 8))
    full, rem = divmod(eighths, 8)
    if full >= width:                 # clamp; never overflow the track
        full, rem = width, 0
    cells = FILL * full
    used = full
    if rem and full < width:
        cells += PARTIALS[rem]
        used += 1
    # C_TRACK paints the grey track once; it persists (foreground codes don't
    # touch the background) until C_RESET, so the partial cell's empty half and
    # the trailing spaces form one continuous grey groove — no glyphs, no notch.
    return f"{C_TRACK}{color}{cells}{EMPTY * (width - used)}{C_RESET}"


def read_window(rate_limits: dict, key: str) -> tuple | None:
    """Validate one rate-limit window -> (used_pct, resets_at|None) or None.

    Defends against documented statusLine bugs: when a window has no data
    yet, `used_percentage` has been observed returning the epoch value
    (#52326) or otherwise-impossible numbers (#31820). Anything outside
    0..100 is treated as 'no data' so the segment is hidden, not garbled.
    """
    win = rate_limits.get(key)
    if not isinstance(win, dict):
        return None
    pct = win.get("used_percentage")
    if not isinstance(pct, (int, float)) or isinstance(pct, bool):
        return None
    if pct < 0 or pct > 100:
        return None
    reset = win.get("resets_at")
    if not isinstance(reset, (int, float)) or isinstance(reset, bool):
        reset = None
    return (float(pct), float(reset) if reset is not None else None)


def superscript(n: int) -> str:
    return "".join(SUP_DIGITS[int(d)] for d in str(int(n)))


def subscript(n: int) -> str:
    return "".join(SUB_DIGITS[int(d)] for d in str(int(n)))


def window_time_frac(reset: float, now: float, duration: int) -> float:
    """Fraction of the rolling window already elapsed (0..1); 1 == at reset."""
    return max(0.0, min(1.0, (duration - (reset - now)) / duration))


def render_dual_block(top_frac: float, bottom_frac: float, width: int) -> str:
    """A `width`-cell bar stacking two rows via quadrant blocks.

    Each cell spans 2 columns, so horizontal resolution is `width * 2`. The
    top row tracks `top_frac` (quota used), the bottom row `bottom_frac`
    (time elapsed): when the top shelf outruns the bottom you are spending
    faster than the clock. Solid quadrant glyphs keep it in the same visual
    family as the context bar.
    """
    top_frac = max(0.0, min(1.0, top_frac))
    bottom_frac = max(0.0, min(1.0, bottom_frac))
    cols = width * 2
    top_cols = int(round(top_frac * cols))
    bot_cols = int(round(bottom_frac * cols))
    out = []
    for i in range(width):
        left, right = 2 * i, 2 * i + 1
        bits = 0
        if left < top_cols:
            bits |= 1           # top-left
        if right < top_cols:
            bits |= 2           # top-right
        if left < bot_cols:
            bits |= 4           # bottom-left
        if right < bot_cols:
            bits |= 8           # bottom-right
        out.append(QUAD[bits])
    return "".join(out)


def window_segment(label: str, pct: float, reset, now: float,
                   duration: int, when: str) -> str:
    """One rate-limit window: stacked dual bar + `used ⁄ time` figure.

    Colour encodes *pace* (used vs time-elapsed), not absolute level: green
    when comfortably under the clock, red when burning ahead of it.
    """
    usage_frac = max(0.0, min(1.0, pct / 100))
    tfrac = window_time_frac(reset, now, duration) if reset is not None else None

    if tfrac is None:                       # no resets_at -> no pace; show level
        color = context_color(usage_frac)
        bar = render_dual_block(usage_frac, 0.0, USAGE_BAR_WIDTH)
        figure = f"{color}{round(pct)}%{C_RESET}"
    else:
        color = pace_color(usage_frac, tfrac)
        bar = render_dual_block(usage_frac, tfrac, USAGE_BAR_WIDTH)
        figure = (f"{color}{superscript(round(pct))}{C_RESET}"
                  f"{C_MUTE}⁄{subscript(round(tfrac * 100))}{C_RESET}")

    seg = f"{label} {C_TRACK}{color}{bar}{C_RESET} {figure}"
    if when:
        seg += f"{C_MUTE} →{when}{C_RESET}"
    return seg


def build_usage(data: dict, now: float) -> str:
    """The `5h .. · 7d ..` segment, or '' when no subscription data is present.

    `rate_limits` is absent for API-key auth and before the first API
    response; each window may also be independently absent. All paths
    degrade silently to an empty string.
    """
    rate_limits = data.get("rate_limits")
    if not isinstance(rate_limits, dict):
        return ""

    parts = []
    five = read_window(rate_limits, "five_hour")
    if five:
        pct, reset = five
        when = fmt_duration(reset - now) if reset is not None else ""
        parts.append(window_segment("5h", pct, reset, now, WIN_5H, when))

    week = read_window(rate_limits, "seven_day")
    if week:
        pct, reset = week
        when = fmt_reset_clock(reset, now) if reset is not None else ""
        parts.append(window_segment("7d", pct, reset, now, WIN_7D, when))

    if not parts:
        return ""
    divider = f"{C_DIM}  │  {C_RESET}"
    sep = f"{C_DIM} · {C_RESET}"
    return divider + sep.join(parts)


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        data = {}

    model = data.get("model") or {}
    model_id = model.get("id", "")
    model_name = model.get("display_name") or model_id or "Claude"
    transcript = data.get("transcript_path", "")
    exceeds_200k = bool(data.get("exceeds_200k_tokens"))

    ctx = last_context_tokens(transcript) if transcript else 0
    limit = detect_limit(model_id, ctx, exceeds_200k)
    pct = ctx / limit if limit else 0.0

    bar = render_bar(pct, BAR_WIDTH)
    pct_txt = f"{round(pct * 100)}%"
    tokens = f"{C_MUTE}{fmt_tokens(ctx)}/{fmt_tokens(limit)}{C_RESET}"
    usage = build_usage(data, time.time())

    print(f"{model_name}  {bar} {pct_txt}  {tokens}{usage}")


if __name__ == "__main__":
    main()
