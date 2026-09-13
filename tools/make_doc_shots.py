#!/usr/bin/env python3
"""README 示例图生成器：合成夹具 → 真实 CLI 输出 → PNG。

为什么需要它：公开仓库里的示例图必须能脱敏复现，不能出现真实会话中的内网模型名与
真实金额。做法是先用确定性的合成夹具（公开模型名 + 公开定价）写出一套 rollout 会话，
再用 CODEX_USAGE_SESSIONS_DIR / CODEX_USAGE_PRICING_FILE 把 CLI 指到夹具上，最后把
终端输出与 matplotlib 真图落成 PNG。脚本不启动任何 GUI 程序，也不读本机的
~/.codex 与 ~/.cc-switch，因此在任何机器上跑出来的图都是同一套合成数据。

用法（在仓库根目录）:
    .venv/bin/python tools/make_doc_shots.py              # 生成全部示例图
    .venv/bin/python tools/make_doc_shots.py --clean      # 先清掉输出目录里的 *.png
    .venv/bin/python tools/make_doc_shots.py --fixture-dir /tmp/demo

产物（默认 docs/shots/）:
    table-bymodel.png        表格：按模型聚合
    chart-bar-kitty.png      真图档：各模型成本柱状图
    chart-bar-halfcell.png   半块档：同一张图在无图形协议终端下的显示
    chart-bar-ascii.png      字符画档：--ascii（标签自动 ASCII 化）
    chart-pie-kitty.png      真图档：成本占比饼图
    chart-area-kitty.png     真图档：每天成本面积图（按模型多序列）
    doctor.png               --doctor 环境自检

终端字节流 → PNG 的渲染是离线做的：解析 ANSI SGR（含 38;5;n / 38;2;r;g;b）后逐格
绘制，半块字符（▀/▄）按前景/背景色各画半个字符格，因此彩色半块图表能忠实还原。
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import pty
import random
import re
import shutil
import struct
import subprocess
import sys
import termios
import time
import unicodedata
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "docs" / "shots"
DEFAULT_FIXTURE = Path(os.environ.get("CODEX_USAGE_DOCS_FIXTURE",
                                      Path(os.environ.get("TMPDIR", "/tmp")) / "codex-usage-doc-fixture"))

# 夹具统一按 UTC+8 生成；子进程固定 TZ=Asia/Shanghai，保证换机器也落进同一个时间窗口
TZ = timezone(timedelta(hours=8))
DEMO_SINCE = "2026-09-04"
DEMO_UNTIL = "2026-09-13"
DAY0, DAY1 = date(2026, 9, 4), date(2026, 9, 13)
FIXED_MTIME = datetime(2026, 9, 13, 23, 36, tzinfo=TZ).timestamp()

COLS, ROWS = 120, 44                     # 演示终端的格子数（写在图上的排版依赖它）

# 三档渲染对比用同一条命令：按天成本的单序列柱状图。单序列没有图例，
# 在 119×84 光栅的半块档下也不会有图例文字糊满绘图区的问题。
BAR_ARGS = ["--chart", "bar", "--by-day", "--metric", "cost"]
# 天×模型堆叠柱：模型名走图例，只出真图（半块档的小光栅放不下长图例）
STACKED_ARGS = ["--chart", "bar", "--by-day", "--by-model", "--metric", "cost"]

# 公开模型与公开定价（USD / 百万 token）。取值来自 models.dev 里对应模型的一手 provider
# 条目（openai/anthropic/google），在这里写死，示例图才不会随内置定价表的更新而漂移。
PRICING = [
    {"modelId": "gpt-5.3-codex", "displayName": "GPT-5.3 Codex",
     "inputCostPerMillion": "1.75", "outputCostPerMillion": "14", "cacheReadCostPerMillion": "0.175"},
    {"modelId": "gpt-5.1-codex", "displayName": "GPT-5.1 Codex",
     "inputCostPerMillion": "1.25", "outputCostPerMillion": "10", "cacheReadCostPerMillion": "0.125"},
    {"modelId": "gpt-5.1-codex-mini", "displayName": "GPT-5.1 Codex mini",
     "inputCostPerMillion": "0.25", "outputCostPerMillion": "2", "cacheReadCostPerMillion": "0.025"},
    {"modelId": "claude-sonnet-5", "displayName": "Claude Sonnet 5",
     "inputCostPerMillion": "2", "outputCostPerMillion": "10", "cacheReadCostPerMillion": "0.2"},
]
MODEL_POOL = [("gpt-5.3-codex", 5), ("gpt-5.1-codex", 4),
              ("gpt-5.1-codex-mini", 2), ("claude-sonnet-5", 2)]
OUT_SCALE = {"gpt-5.3-codex": 1.0, "gpt-5.1-codex": 1.0,
             "gpt-5.1-codex-mini": 0.7, "claude-sonnet-5": 1.2}

# ------------------------------- 终端渲染 -------------------------------

FONT_CANDIDATES = (
    "/usr/share/fonts/google-noto-sans-mono-cjk-vf-fonts/NotoSansMonoCJK-VF.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansMonoCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansMonoCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansMonoCJK-Regular.ttc",
)
CW, CH = 9, 20                            # 字符格像素（字号按这个格子定）
FONT_SIZE = 15
DEFAULT_BG = (24, 24, 24)
DEFAULT_FG = (205, 205, 205)
BASE16 = [(0, 0, 0), (205, 49, 49), (13, 188, 121), (229, 229, 16), (36, 114, 200),
          (188, 63, 188), (17, 168, 205), (229, 229, 229), (102, 102, 102), (241, 76, 76),
          (35, 209, 139), (245, 245, 67), (59, 142, 234), (214, 112, 214), (41, 184, 219),
          (255, 255, 255)]
SGR = re.compile("\x1b\\[([0-9;]*)m")


def find_font(explicit: str | None = None) -> str | None:
    """挑一个带 CJK 与制表符字形的等宽字体（终端截图里有中文与框线）。"""
    if explicit:
        return explicit
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            return path
    if shutil.which("fc-match"):
        try:
            out = subprocess.run(["fc-match", "-f", "%{file}", "Noto Sans Mono CJK SC"],
                                 capture_output=True, text=True, timeout=10)
            hit = out.stdout.strip()
            if hit and os.path.isfile(hit):
                return hit
        except Exception:
            pass
    return None


def xterm256(i: int) -> tuple[int, int, int]:
    if i < 16:
        return BASE16[i]
    if i < 232:
        i -= 16
        return (i // 36 * 51, i // 6 % 6 * 51, i % 6 * 51)
    v = 8 + (i - 232) * 10
    return (v, v, v)


def clean_stream(raw: bytes) -> str:
    """剔除光标/清屏/OSC/DCS(Sixel) 等控制序列，只保留 SGR（以 m 结尾的 CSI）。

    不能简单用 `\\x1b\\[[0-9;?]*[@-~]` 统一删除：该字符类包含 `m`，会把 SGR 颜色
    序列一起删掉（渲染结果就变成灰阶）。
    """
    out = bytearray()
    i, n = 0, len(raw)
    while i < n:
        b = raw[i]
        if b == 0x1B and i + 1 < n:
            nxt = raw[i + 1]
            if nxt == 0x5B:                                  # CSI
                j = i + 2
                while j < n and not (0x40 <= raw[j] <= 0x7E):
                    j += 1
                if j < n and raw[j] == ord("m"):
                    out += raw[i:j + 1]
                i = j + 1
                continue
            if nxt == 0x5D:                                  # OSC
                j = i + 2
                while j < n and raw[j] != 0x07 and raw[j] != 0x1B:
                    j += 1
                i = j + 2 if j + 1 < n and raw[j] == 0x1B else j + 1
                continue
            if nxt in (0x50, 0x58, 0x5E, 0x5F):              # DCS / SOS / PM / APC
                j = i + 2
                while j + 1 < n and not (raw[j] == 0x1B and raw[j + 1] == 0x5C):
                    j += 1
                i = j + 2
                continue
            i += 2
            continue
        out.append(b)
        i += 1
    return out.decode("utf-8", "replace").replace("\r\n", "\n")


def parse_colors(text: str) -> list[list[tuple[str, tuple, tuple | None, bool]]]:
    """完整 SGR 解析（含 38;5;n / 48;5;n / 38;2;r;g;b），返回按行的 cell 列表。"""
    lines = []
    for line in text.split("\n"):
        cells = []
        fg, bg, bold = DEFAULT_FG, None, False
        i = 0
        while i < len(line):
            if line[i] == "\r":
                cells, i = [], i + 1
                continue
            m = SGR.match(line, i)
            if m:
                codes = [int(c or 0) for c in (m.group(1) or "0").split(";")]
                j = 0
                while j < len(codes):
                    c = codes[j]
                    if c == 0:
                        fg, bg, bold = DEFAULT_FG, None, False
                    elif c == 1:
                        bold = True
                    elif c == 22:
                        bold = False
                    elif c == 39:
                        fg = DEFAULT_FG
                    elif c == 49:
                        bg = None
                    elif c == 7:
                        fg, bg = (bg or DEFAULT_BG), fg
                    elif 30 <= c <= 37:
                        fg = BASE16[c - 30]
                    elif 90 <= c <= 97:
                        fg = BASE16[c - 90 + 8]
                    elif 40 <= c <= 47:
                        bg = BASE16[c - 40]
                    elif 100 <= c <= 107:
                        bg = BASE16[c - 100 + 8]
                    elif c in (38, 48) and j + 1 < len(codes):
                        target = fg if c == 38 else bg
                        if codes[j + 1] == 5 and j + 2 < len(codes):
                            target = xterm256(codes[j + 2])
                            j += 2
                        elif codes[j + 1] == 2 and j + 4 < len(codes):
                            target = tuple(codes[j + 2:j + 5])
                            j += 4
                        if c == 38:
                            fg = target
                        else:
                            bg = target
                    j += 1
                i = m.end()
                continue
            ch = line[i]
            i += 1
            wide = 2 if unicodedata.east_asian_width(ch) in "WF" else 1
            cells.append((ch, fg, bg, bold))
            for _ in range(wide - 1):
                cells.append(("", fg, bg, bold))
        while cells and cells[-1][0] in ("", " ") and cells[-1][2] is None:
            cells.pop()
        lines.append(cells)
    return lines


def render_terminal(raw: bytes, out_path: Path, font_path: str | None = None,
                    max_lines: int | None = None) -> tuple[int, int]:
    """终端字节流 → PNG，返回 (宽, 高) 像素。"""
    from PIL import Image, ImageDraw, ImageFont

    lines = parse_colors(clean_stream(raw))
    if max_lines:
        lines = lines[:max_lines]
    cols = max((len(cells) for cells in lines), default=1)
    rows = len(lines)
    img = Image.new("RGB", (cols * CW, rows * CH), DEFAULT_BG)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(font_path, FONT_SIZE) if font_path else ImageFont.load_default()
    except OSError:
        font = ImageFont.load_default()
    half = CH // 2
    for r, cells in enumerate(lines):
        y = r * CH
        for c, (ch, fg, bg, _bold) in enumerate(cells):
            x = c * CW
            if bg is not None:
                draw.rectangle([x, y, x + CW - 1, y + CH - 1], fill=bg)
            if ch == "\u2580":                       # 上半块
                draw.rectangle([x, y, x + CW - 1, y + half - 1], fill=fg)
            elif ch == "\u2584":                     # 下半块
                draw.rectangle([x, y + half, x + CW - 1, y + CH - 1], fill=fg)
            elif ch not in ("", " "):
                draw.text((x, y - 2), ch, font=font, fill=fg)
    img.save(out_path)
    return img.size[0], img.size[1]


# ------------------------------- 合成夹具 -------------------------------

def _iso(local_dt: datetime) -> str:
    """本地时间 → rollout 里的 UTC ISO 时间戳。"""
    return local_dt.astimezone(TZ).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _uuid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"codex-usage/doc-shots/{name}"))


def _line(ts: str, typ: str, payload: dict) -> str:
    return json.dumps({"timestamp": ts, "type": typ, "payload": payload})


def _usage(net: int, cached: int, out: int) -> dict:
    """net 是净输入；rollout 里的 input_tokens 是含缓存的毛值。"""
    return {"input_tokens": net + cached, "cached_input_tokens": cached,
            "output_tokens": out, "reasoning_output_tokens": out // 2}


def _write_rollout(path: Path, sid: str, model: str, start: datetime, rounds: list[tuple[int, int, int]],
                   parent: str | None = None, nickname: str | None = None,
                   role: str | None = None) -> None:
    """一个会话一个 rollout 文件：session_meta → 逐轮 turn_context/token_count。"""
    if parent:
        src: object = {"subagent": {"thread_spawn": {
            "parent_thread_id": parent, "depth": 1,
            "agent_nickname": nickname, "agent_role": role}}}
        thread_source = "subagent"
    else:
        src = "vscode"
        thread_source = "user"
    meta = {"session_id": sid, "id": sid, "cwd": "/home/dev/demo-project",
            "originator": "Codex Desktop", "source": src,
            "thread_source": thread_source, "model_provider": "openai"}
    body = [_line(_iso(start), "session_meta", meta)]
    cum = [0, 0, 0]
    for k, (net, cached, out) in enumerate(rounds):
        ts = start + timedelta(minutes=4 * k + 1)
        body.append(_line(_iso(ts), "turn_context", {"model": model}))
        cum = [cum[0] + net + cached, cum[1] + cached, cum[2] + out]
        body.append(_line(_iso(ts), "event_msg", {
            "type": "token_count",
            "info": {"last_token_usage": _usage(net, cached, out),
                     "total_token_usage": {"input_tokens": cum[0],
                                           "cached_input_tokens": cum[1],
                                           "output_tokens": cum[2]}}}))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    os.utime(path, (FIXED_MTIME, FIXED_MTIME))


def _pick_model(rng: random.Random) -> str:
    names, weights = zip(*MODEL_POOL)
    return rng.choices(names, weights=weights, k=1)[0]


def _rounds_for(rng: random.Random, model: str, day_index: int) -> list[tuple[int, int, int]]:
    """按模型造一段逐轮用量：缓存读随上下文增长，净输入与输出围绕小范围波动。"""
    n = rng.randint(6, 26)
    cached = rng.randint(6_000, 24_000)
    out: list[tuple[int, int, int]] = []
    for _ in range(n):
        cached = min(cached + rng.randint(1_500, 11_000), 220_000)
        net = rng.randint(150, 1_400)
        o = int(rng.randint(120, 1_100) * OUT_SCALE[model] * (1 + 0.06 * day_index))
        out.append((net, cached, o))
    return out


def build_fixture(fixture_dir: Path) -> dict:
    """写一套确定性的合成会话 + 定价表，返回各数据路径与 rollout 文件数。"""
    sessions = fixture_dir / "sessions"
    archive = fixture_dir / "archived_sessions"
    pricing = fixture_dir / "model-pricing.json"
    raw_dir = fixture_dir / "raw"
    for d in (sessions, archive, raw_dir):
        d.mkdir(parents=True, exist_ok=True)
    pricing.write_text(json.dumps({"models": PRICING}, ensure_ascii=False, indent=2), encoding="utf-8")
    os.utime(pricing, (FIXED_MTIME, FIXED_MTIME))    # --doctor 会显示定价表的数据日期，固定住

    rng = random.Random(20260913)
    day = DAY0
    idx = 0
    n_files = 0
    while day <= DAY1:
        for _ in range(rng.randint(2, 4)):
            idx += 1
            start = datetime(day.year, day.month, day.day,
                             rng.randint(9, 21), rng.randint(0, 59), tzinfo=TZ)
            model = _pick_model(rng)
            sid = _uuid(f"session-{idx}")
            fname = f"rollout-{start.strftime('%Y-%m-%dT%H-%M-%S')}-{sid}.jsonl"
            _write_rollout(sessions / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}" / fname,
                           sid, model, start, _rounds_for(rng, model, (day - DAY0).days))
            n_files += 1
        day += timedelta(days=1)

    # 一对父子会话：父线程 + 子代理（文件名两个 UUID，父在前、子代理在后）
    parent_sid, child_sid = _uuid("parent-main"), _uuid("child-feynman")
    fmt = "%Y-%m-%dT%H-%M-%S"
    p = sessions / "2026" / "09" / "12"
    parent_start = datetime(2026, 9, 12, 14, 10, tzinfo=TZ)
    _write_rollout(p / f"rollout-{parent_start.strftime(fmt)}-{parent_sid}.jsonl",
                   parent_sid, "gpt-5.1-codex", parent_start,
                   _rounds_for(rng, "gpt-5.1-codex", 8))
    child_start = datetime(2026, 9, 12, 14, 26, tzinfo=TZ)
    _write_rollout(p / f"rollout-{child_start.strftime(fmt)}-{parent_sid}_{child_sid}.jsonl",
                   child_sid, "claude-sonnet-5", child_start,
                   _rounds_for(rng, "claude-sonnet-5", 8),
                   parent=parent_sid, nickname="Feynman", role="reviewer")
    n_files += 2

    os.utime(sessions, (FIXED_MTIME, FIXED_MTIME))
    os.utime(archive, (FIXED_MTIME, FIXED_MTIME))
    return {"sessions": str(sessions), "archive": str(archive), "pricing": str(pricing),
            "raw": str(raw_dir), "files": n_files}


# ------------------------------- CLI 采集 -------------------------------

def cli_env(fixture: dict, cols: int = COLS, rows: int = ROWS) -> dict:
    env = {**os.environ,
           "TERM": "xterm-256color", "COLUMNS": str(cols), "LINES": str(rows),
           "TZ": "Asia/Shanghai",
           "PYTHONPATH": str(ROOT / "src"),
           "MPLCONFIGDIR": str(Path(fixture["sessions"]).parent / "matplotlib"),
           "CODEX_USAGE_SESSIONS_DIR": fixture["sessions"],
           "CODEX_USAGE_ARCHIVE_DIR": fixture["archive"],
           "CODEX_USAGE_PRICING_FILE": fixture["pricing"]}
    env.pop("NO_COLOR", None)                    # 截图要看颜色
    env.pop("CODEX_USAGE_IMAGE_MODE", None)      # 档位由各用例显式指定
    Path(env["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    return env


def run_cli_pty(argv: list[str], env: dict, cols: int = COLS, rows: int = ROWS) -> bytes:
    """用真实 pty 跑一段 CLI，捕获合并后的终端字节流（含 ANSI）。"""
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    proc = subprocess.Popen([sys.executable, "-m", "codex_usage.cli", *argv],
                            stdin=slave, stdout=slave, stderr=slave, env=env, cwd=str(ROOT))
    os.close(slave)
    chunks = []
    while True:
        try:
            data = os.read(master, 65536)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)
    raw = b"".join(chunks)
    os.close(master)
    code = proc.wait()
    if code != 0:
        tail = raw.decode("utf-8", "replace").strip().splitlines()[-4:]
        raise SystemExit(f"CLI 退出码 {code}: {' '.join(argv)}\n" + "\n".join(tail))
    return raw


def export_true_images(out_dir: Path, fixture: dict) -> None:
    """真图档：直接复用 CLI 的 matplotlib 出图路径，把 Figure 存成 PNG。

    终端里的真图就是同一份 Figure 经图形协议（kitty TGP / Sixel）送出去的，
    这里把 _render 换成「收集 Figure」，存下来的即终端显示的那张原图（1200×700）。
    """
    sys.path.insert(0, str(ROOT / "src"))
    os.environ["CODEX_USAGE_SESSIONS_DIR"] = fixture["sessions"]
    os.environ["CODEX_USAGE_ARCHIVE_DIR"] = fixture["archive"]
    os.environ["CODEX_USAGE_PRICING_FILE"] = fixture["pricing"]

    from codex_usage import cli, config                          # noqa: E402
    from codex_usage.parser import collect                       # noqa: E402
    from codex_usage.pricing import load_pricing                 # noqa: E402
    from codex_usage.render import imgcharts as m                # noqa: E402

    recs = collect(config.sessions_dir(), datetime(2026, 9, 4), datetime(2026, 9, 13, 23, 59, 59))
    pricing = load_pricing()
    parser = cli.build_parser()

    figs: list = []

    def _target_px() -> tuple[int, int]:
        return 1200, 700                             # 图形协议终端下的像素光栅

    def _collect(fig):
        figs.append(fig)
        return fig                                   # 替掉 _render：只收 Figure，不送终端

    m._target_px = _target_px
    m._render = _collect

    cases = {
        "chart-bar-kitty": list(BAR_ARGS),
        "chart-bar-stacked-kitty": list(STACKED_ARGS),
        "chart-pie-kitty": ["--chart", "pie", "--metric", "cost"],
        "chart-area-kitty": ["--chart", "area", "--by-day", "--by-model", "--metric", "cost"],
    }
    print(f"夹具会话数: {len(recs)}（窗口 {DEMO_SINCE} ~ {DEMO_UNTIL}）")
    for name, argv in cases.items():
        args = parser.parse_args(argv)
        figs.clear()
        cli._chart_draw(args, recs, pricing, m, lambda _r: None)
        fig = figs[-1]
        path = out_dir / f"{name}.png"
        fig.savefig(path, dpi=m._DPI)
        print(f"  {name:<20} {fig.get_size_inches()[0] * m._DPI:.0f}x"
              f"{fig.get_size_inches()[1] * m._DPI:.0f}px")
        figs.clear()


# ------------------------------- 主流程 -------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="生成脱敏的 README 示例图（合成数据 → 真实 CLI 输出 → PNG）")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="输出目录（默认 docs/shots）")
    ap.add_argument("--fixture-dir", default=str(DEFAULT_FIXTURE), help="合成夹具目录（默认 $TMPDIR/codex-usage-doc-fixture）")
    ap.add_argument("--font", default=None, help="终端截图用的字体文件（默认自动探测 CJK 等宽字体）")
    ap.add_argument("--clean", action="store_true", help="生成前先删掉输出目录里的 *.png")
    args = ap.parse_args()

    if os.name != "posix":                        # pty 只在类 Unix 上可用
        print("本脚本需要 POSIX pty（Linux/macOS）", file=sys.stderr)
        return 1
    os.environ["TZ"] = "Asia/Shanghai"
    time.tzset()

    out_dir = Path(args.out).resolve()
    fixture_dir = Path(args.fixture_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    # matplotlib 默认配置目录可能在只读的家目录下，指向夹具目录避免导入期告警
    os.environ["MPLCONFIGDIR"] = str(fixture_dir / "matplotlib")
    if args.clean:
        for old in out_dir.glob("*.png"):
            old.unlink()
    font = find_font(args.font)
    if not font:
        print("提示: 未找到 CJK 等宽字体，中文与框线可能显示为方框", file=sys.stderr)

    fixture = build_fixture(fixture_dir)
    env = cli_env(fixture)
    raw_dir = Path(fixture["raw"])
    print(f"夹具: {fixture_dir}（{fixture['files']} 个 rollout 文件）")

    window = ["--since", DEMO_SINCE, "--until", DEMO_UNTIL]
    capture_cases = [
        # (产物名, CLI 参数, CODEX_USAGE_IMAGE_MODE, 截断行数, 是否带演示时间窗口)
        ("table-bymodel", ["--by-model"], None, 30, True),
        ("chart-bar-halfcell", list(BAR_ARGS), "halfcell", None, True),
        ("chart-bar-ascii", [*BAR_ARGS, "--ascii"], None, None, True),
        ("doctor", ["--doctor"], None, None, False),
    ]
    for name, argv, mode, limit, windowed in capture_cases:
        run_env = dict(env)
        if mode:
            run_env["CODEX_USAGE_IMAGE_MODE"] = mode
        raw = run_cli_pty([*(window if windowed else []), *argv], run_env)
        (raw_dir / f"{name}.raw").write_bytes(raw)
        w, h = render_terminal(raw, out_dir / f"{name}.png", font, limit)
        print(f"  {name:<20} {w}x{h}px  原始 {len(raw)}B")

    export_true_images(out_dir, fixture)
    print(f"完成：{out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
