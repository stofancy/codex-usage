"""真图图表：matplotlib 渲成 PNG，再由 textual-image 在终端显示（可选依赖）。

与 charts.py 的三个绘图函数同签名，cli 按运行环境二选一：装了 `codex-usage[image]`、
输出是终端且未指定 `--ascii` 时走本模块，其余情况回退字符画。
显示方式由 textual-image 自动选择：支持图形协议（kitty TGP / Sixel）的终端出真图，
其他终端出彩色半块字符。

出图分辨率按终端能显示的光栅尺寸定（图形协议：格子数×每格像素；半块：1 像素/半格），
小光栅再 2 倍超采样后由 textual-image 缩回，避免把 PNG 缩放十几倍后细线被抹平。
"""

import io
import logging
import os
import shutil
import sys
import unicodedata
from functools import lru_cache

from .charts import METRIC_LABEL, metric_of

# 中文字体候选：命中第一个即用（matplotlib 默认字体无 CJK 字形，中文会变方框）
_CJK_FONTS = ("Noto Sans CJK SC", "Source Han Sans SC", "Noto Sans CJK JP", "WenQuanYi Zen Hei",
              "WenQuanYi Micro Hei", "Droid Sans Fallback", "Microsoft YaHei", "PingFang SC")

_COLORS = ("#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
           "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac")

_GRID = "#dddddd"
_DPI = 100
_MAX_COLS, _MAX_LINES = 240, 80      # 光栅上限，防 COLUMNS/LINES 异常放大
_FALLBACK_PX = (1400, 590)
_MAX_TICKS = 12                      # x 轴最多保留的标签数（多则抽稀）


class _ProbeStdout:
    """终端探测期的 `sys.__stdout__` 替身：只改写入目标，终端语义沿用真实 stdout。

    textual-image 在导入时按 `sys.__stdout__.isatty()` 选定渲染档位，并向它写能力查询。
    若直接把 `__stdout__` 换成 stderr，`codex-usage --chart … 2>/dev/null` 会被判成
    「非终端」而永久降级成字符回退，--doctor 也会报错档位；这里只把查询序列改投 stderr
    （终端照样应答），isatty/size 仍看真实 stdout，stdout 的数据流保持干净。
    """

    def __init__(self, real, sink):
        self._real, self._sink = real, sink

    def write(self, data):
        return self._sink.write(data)

    def flush(self):
        return self._sink.flush()

    def isatty(self):
        return self._real.isatty()

    def fileno(self):
        return self._sink.fileno()

    @property
    def encoding(self):
        return getattr(self._real, "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(self._real, "errors", "replace")


@lru_cache(maxsize=1)
def _renderable():
    """textual-image 的 renderable 模块（导入期会探测终端能力）。

    探测序列由 textual-image 直接写 `sys.__stdout__`；把它引到 stderr，避免混进
    `--json`/`--schema`/`--doctor` 的 stdout 数据流（Agent 会直接解析这些输出）。
    """
    original, sink = sys.__stdout__, sys.stderr
    try:
        if original is not None and sink is not None:
            sys.__stdout__ = _ProbeStdout(original, sink)
        from textual_image import renderable
    finally:
        sys.__stdout__ = original
    return renderable


@lru_cache(maxsize=1)
def available() -> bool:
    """图片渲染依赖（matplotlib + textual-image）是否可用。"""
    _configure()                      # 必须在导入之前：matplotlib 导入期就会发配置目录告警
    try:
        import matplotlib  # noqa: F401
        _renderable()
    except Exception:
        return False
    return True


@lru_cache(maxsize=1)
def _cjk_font() -> str | None:
    """配置并返回可用的中文字体名；系统没有 CJK 字体时返回 None。"""
    from matplotlib import font_manager, rcParams

    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in _CJK_FONTS:
        if name in installed:
            rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            rcParams["axes.unicode_minus"] = False
            return name
    return None


@lru_cache(maxsize=1)
def _configure() -> str | None:
    """一次性初始化：压掉库自身的诊断告警，返回选中的中文字体名。

    matplotlib 的缺字/配置目录告警、textual-image 探测终端格子尺寸失败时的告警
    （带堆栈）对使用者没有可操作信息，只会夹在图表或 --doctor 输出里刷屏。
    """
    for name in ("matplotlib", "matplotlib.font_manager", "textual_image"):
        logging.getLogger(name).setLevel(logging.ERROR)
    try:
        return _cjk_font()
    except Exception:                 # matplotlib 未安装：静音后返回「无字体」即可
        return None


@lru_cache(maxsize=1)
def _warn_missing_cjk() -> None:
    print("提示: 系统未找到中文字体，图表中的中文可能显示为方框（可安装 Noto Sans CJK）",
          file=sys.stderr)


IMAGE_MODES = ("auto", "tgp", "sixel", "halfcell", "ascii")

_MODE_DISPLAY = {"tgp": "真图（kitty 图形协议）", "sixel": "真图（Sixel）",
                 "halfcell": "彩色半块", "ascii": "字符回退"}


def image_mode() -> str:
    """渲染档位：auto（默认）| tgp | sixel | halfcell | ascii。

    由环境变量 CODEX_USAGE_IMAGE_MODE 指定；非法值按 auto 处理。遇到把真图渲染坏的终端
    可以一键降级（halfcell/ascii），不必整个退到 --ascii 字符画。
    """
    mode = os.environ.get("CODEX_USAGE_IMAGE_MODE", "auto").strip().lower()
    return mode if mode in IMAGE_MODES else "auto"


def image_class(renderable=None):
    """按档位选 textual-image 的渲染类（auto 时用其自动探测结果）。"""
    r = renderable or _renderable()
    forced = _MODE_DISPLAY.get(image_mode())
    if forced is None:
        return r.Image
    return {"真图（kitty 图形协议）": r.TGPImage, "真图（Sixel）": r.SixelImage,
            "彩色半块": r.HalfcellImage, "字符回退": r.UnicodeImage}[forced]


@lru_cache(maxsize=1)
def describe() -> dict:
    """真图渲染现状（给 --doctor / --schema 用）：依赖、档位、光栅尺寸、中文字体。"""
    info: dict = {"available": available(), "mode": image_mode(), "matplotlib": None,
                  "textual_image": None, "display": None, "detected": None,
                  "raster_px": None, "cjk_font": None}
    if not info["available"]:
        return info
    import matplotlib

    _configure()
    renderable = _renderable()
    info["matplotlib"] = matplotlib.__version__
    try:
        from importlib.metadata import version
        info["textual_image"] = version("textual-image")
    except Exception:
        pass
    info["detected"] = {renderable.TGPImage: "真图（kitty 图形协议）",
                        renderable.SixelImage: "真图（Sixel）",
                        renderable.HalfcellImage: "彩色半块",
                        renderable.UnicodeImage: "字符回退"}.get(renderable.Image, "未知")
    info["display"] = _MODE_DISPLAY.get(info["mode"]) or info["detected"]
    info["cjk_font"] = _cjk_font()
    try:
        info["raster_px"] = list(_target_px())
    except Exception:
        pass
    return info


@lru_cache(maxsize=1)
def _target_px() -> tuple[int, int]:
    """终端能显示的图表光栅像素尺寸；拿不到终端信息时退回固定尺寸。"""
    cols = max(40, min(_MAX_COLS, shutil.get_terminal_size().columns - 1))
    lines = max(12, min(_MAX_LINES, shutil.get_terminal_size().lines - 2))
    try:
        from textual_image._terminal import get_cell_size
        renderable = _renderable()
        cls = image_class(renderable)
        if cls is renderable.UnicodeImage:
            return cols, lines                # 字符回退：1 字符 = 1 像素
        if cls is renderable.HalfcellImage:
            return cols, lines * 2            # 半块：每格 1 像素宽、2 像素高
        cell_w, cell_h = get_cell_size()
        return cols * cell_w, lines * cell_h
    except Exception:
        return _FALLBACK_PX


def _sizes(px_w: int, px_h: int) -> dict:
    """字号（终端显示像素）/ 线宽（出图像素）：小图保底可辨，大图不出怪比例。"""
    k = 2 if px_w < 900 else 1
    return {"k": k, "px_w": px_w, "px_h": px_h,
            "title_px": min(20.0, max(8.0, 0.032 * px_h)),
            "tick_px": min(16.0, max(7.0, 0.026 * px_h)),
            "lw": max(1.6, 0.0035 * px_h * k),
            "ms": max(3.5, 0.011 * px_h * k)}


def _text_w(text: str, font_px: float) -> float:
    """文本宽度估算（显示像素）：CJK 约 1.0 字宽，其余约 0.6。"""
    wide = sum(1 for c in text if unicodedata.east_asian_width(c) in "WF")
    return font_px * (wide + 0.60 * (len(text) - wide))


def _fit_text(text: str, avail_px: float, font_px: float) -> str:
    """按可用宽度截断文本（加省略号）：matplotlib 不裁剪文字，超出画布即不显示。"""
    if _text_w(text, font_px) <= avail_px:
        return text
    cut = text
    while cut and _text_w(cut + "…", font_px) > avail_px:
        cut = cut[:-1]
    return (cut + "…") if cut else "…"


def _fit_names(names: list[str], avail_px: float, font_px: float) -> list[str]:
    return [_fit_text(n, avail_px, font_px) for n in names]


def _num(v: float) -> str:
    """轴刻度压到 1B/1.5M/120K 这类短写法：终端宽度有限，满写数字会挤掉绘图区。"""
    a = abs(v)
    if a >= 1e9:
        return f"{v / 1e9:.1f}B"
    if a >= 1e6:
        return f"{v / 1e6:.1f}M"
    if a >= 1e3:
        return f"{v / 1e3:.0f}K"
    if a == 0:
        return "0"
    return f"{v:,.2f}" if a >= 0.01 else f"{v:.3g}"


def _figure(title: str, labels: list[str] | None = None, right: float = 0.98,
            extra_bottom_px: float = 0.0):
    """建 Figure（Agg，不依赖 pyplot 全局状态），返回 (fig, ax, sz)。

    边距按字号与标签实际占位（显示像素）算，不拍系数：字号已按显示像素保底，小图
    留不够就会把标题/刻度/图例挤出画布（matplotlib 不裁剪文字，超出即不绘制）。
    极小终端下所需边距会超过画布，按比例压缩，别让 subplots_adjust 报错。
    """
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import FuncFormatter

    _configure()
    if _cjk_font() is None:
        _warn_missing_cjk()
    px_w, px_h = _target_px()
    sz = _sizes(px_w, px_h)
    k = sz["k"]
    fig = Figure(figsize=(px_w * k / _DPI, px_h * k / _DPI), dpi=_DPI)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot(111)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _num(v)))
    ax.tick_params(labelsize=sz["tick_px"] * k * 72 / _DPI)
    ax.grid(axis="y", color=_GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    tick = sz["tick_px"]
    _, shown, rotate = _x_layout(labels or [], sz)
    bottom_px = 1.9 * tick + extra_bottom_px
    if rotate:                                  # 斜排标签的垂直投影也要留出来
        bottom_px += _text_w(max(shown, key=len, default=""), tick) * 0.72
    right = min(0.98, max(0.5, right))
    top = max(0.25, 1 - max(0.10, 1.9 * sz["title_px"] / px_h))
    bottom = max(0.02, min(bottom_px / px_h, top - 0.15))
    left = max(0.02, min(max(0.10, 3.4 * tick / px_w), right - 0.15))
    # 标题居中于坐标轴，左侧边距会让轴心偏右：按「轴心到画布右缘」留出标题可用宽度
    ax.set_title(_fit_text(title, px_w * (1 - (left + right) / 2) * 2 - 6, sz["title_px"]),
                 fontsize=sz["title_px"] * k * 72 / _DPI)
    fig.subplots_adjust(top=top, bottom=bottom, left=left, right=right)
    return fig, ax, sz


def _font_pt(px: float, sz: dict) -> float:
    """显示像素 → 出图字号（pt）。"""
    return px * sz["k"] * 72 / _DPI


def _render(fig):
    """Figure → textual-image 的 Rich renderable（宽高自适应终端，保持比例）。"""
    buf = io.BytesIO()
    fig.canvas.print_png(buf)
    buf.seek(0)
    return image_class()(buf, width="auto", height="auto")


def _x_layout(labels: list[str], sz: dict) -> tuple[list[int], list[str], bool]:
    """x 轴刻度布局 → (下标, 显示标签, 是否斜排)。

    先按 45° 斜排后的水平占宽估算这条轴放得下几个标签，再等距抽稀；抽稀后仍多或标签偏长就斜排。
    """
    if not labels:
        return [], [], False
    widest = max(_text_w(x, sz["tick_px"]) for x in labels)
    room = max(2, min(_MAX_TICKS, int(sz["px_w"] * 0.96 / max(1.0, widest * 0.72))))
    step = max(1, -(-len(labels) // room))
    idx = list(range(0, len(labels), step))
    shown = [labels[i] for i in idx]
    return idx, shown, len(shown) > 5 or max(len(x) for x in shown) > 6


def _xticks(ax, labels: list[str], sz: dict) -> None:
    """设置 x 轴刻度：抽稀 + 斜排；斜排时首尾标签朝画布内对齐，避免左右越界。"""
    idx, shown, rotate = _x_layout(labels, sz)
    ax.set_xticks(idx, shown)
    if not rotate:
        return
    ax.tick_params(axis="x", labelrotation=45, rotation_mode="anchor")
    ticks = ax.get_xticklabels()
    for t in ticks:
        t.set_ha("right")                       # 斜排锚在刻度上并向左下延伸，末位不再右溢
    if ticks:
        ticks[0].set_ha("left")


def chart_pie(model_agg: dict[str, list], metric: str):
    data = {m: round(metric_of(a, metric), 4) for m, a in model_agg.items()}
    data = {m: v for m, v in data.items() if v}
    if not data:
        return "(无数据可画)"
    px_w, px_h = _target_px()
    legend_px = _sizes(px_w, px_h)["tick_px"] * 0.9
    names = list(data)
    widest = max(names, key=len)
    # 图例优先放右侧单列；右侧放不下就放画布底部多列，并按列宽截断名字——宁可字短也不让画布裁掉
    box_w = _text_w(widest, legend_px) + 3.0 * legend_px
    if box_w <= 0.42 * px_w:
        right, extra_bottom, ncols = max(0.5, 1 - box_w / px_w), 0.0, 0
    else:
        right, ncols = 0.98, max(1, int(px_w * 0.96 //
                                      max(1.0, _text_w(widest, legend_px) + 2.5 * legend_px)))
        names = _fit_names(names, px_w * 0.96 / ncols - 2.5 * legend_px, legend_px)
        extra_bottom = -(-len(names) // ncols) * 1.6 * legend_px
    fig, ax, sz = _figure(f"{METRIC_LABEL[metric]} 分布", right=right, extra_bottom_px=extra_bottom)
    vals = list(data.values())
    colors = [_COLORS[i % len(_COLORS)] for i in range(len(names))]
    # 模型名走图例：扇区标签在模型多时会互相压字
    wedges, *_ = ax.pie(vals, colors=colors, startangle=90, counterclock=False,
                        autopct="%1.1f%%", pctdistance=0.78,
                        textprops={"fontsize": _font_pt(legend_px, sz)},
                        wedgeprops={"linewidth": 0.6, "edgecolor": "white"})
    if ncols:                                  # 底部图例用画布坐标，才能对齐画布而不是坐标轴
        fig.legend(wedges, names, loc="lower center", bbox_to_anchor=(0.5, 0.0),
                   ncols=min(ncols, len(names)), fontsize=_font_pt(legend_px, sz))
    else:
        ax.legend(wedges, names, loc="center left", bbox_to_anchor=(1.0, 0.5),
                  fontsize=_font_pt(legend_px, sz))
        fig.canvas.draw()                      # 右列图例按实测宽度回填右边距，估算不留余量会裁字
        need = ax.get_legend().get_window_extent(fig.canvas.get_renderer()).width
        right = max(0.35, min(right, 1 - (need + 6) / (fig.get_figwidth() * _DPI)))
        fig.subplots_adjust(left=min(fig.subplotpars.left, right - 0.15), right=right)
    ax.axis("equal")
    return _render(fig)


def chart_bar(labels: list[str], series: dict[str, list], stacked: bool, title: str):
    if not series:
        return "(无数据可画)"
    fig, ax, sz = _figure(title, labels=labels)
    names = list(series)
    values = [list(series[n]) for n in names]
    x = list(range(len(labels)))
    if len(names) == 1:
        ax.bar(x, values[0], color=_COLORS[0], width=0.62)
    elif stacked:
        bottom = [0.0] * len(labels)
        for i, name in enumerate(names):
            ax.bar(x, values[i], bottom=bottom, color=_COLORS[i % len(_COLORS)],
                   width=0.62, label=name)
            bottom = [b + v for b, v in zip(bottom, values[i])]
        ax.legend(fontsize=_font_pt(sz["tick_px"], sz))
    else:
        step = 0.8 / len(names)
        for i, name in enumerate(names):
            ax.bar([xi - 0.4 + step * (i + 0.5) for xi in x], values[i],
                   color=_COLORS[i % len(_COLORS)], width=step, label=name)
        ax.legend(fontsize=_font_pt(sz["tick_px"], sz))
    _xticks(ax, labels, sz)
    return _render(fig)


def chart_series(kind: str, day_labels: list[str], series: dict[str, list], title: str):
    if not series:
        return "(无数据可画)"
    fig, ax, sz = _figure(title, labels=day_labels)
    x = list(range(len(day_labels)))
    for i, (name, vals) in enumerate(series.items()):
        color = _COLORS[i % len(_COLORS)]
        ax.plot(x, vals, color=color, marker="o" if len(vals) <= _MAX_TICKS else None,
                markersize=sz["ms"], linewidth=sz["lw"], label=name)
        if kind == "area":
            ax.fill_between(x, vals, color=color, alpha=0.18)
    _xticks(ax, day_labels, sz)
    ax.margins(x=0.10)                         # 末位日期标签居中于刻度，留边避免右溢画布
    if len(series) > 1:
        ax.legend(fontsize=_font_pt(sz["tick_px"], sz))
    return _render(fig)
