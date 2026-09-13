"""真图渲染单测：matplotlib → PNG → textual-image（未装 image extras 时整组跳过）。"""

import io
import os
import warnings

import pytest

pytest.importorskip("matplotlib")
pytest.importorskip("textual_image")

from PIL import Image  # noqa: E402
from rich.console import Console  # noqa: E402

from codex_usage.render import imgcharts  # noqa: E402

LABELS = ["09-06", "09-07", "09-08", "09-09", "09-10", "09-11", "09-12"]
DAYS20 = [f"09-{d:02d}" for d in range(1, 21)]
SERIES = {"sol": [1.0, 2.0, 0.5, 3.0, 2.2, 1.8, 4.0],
          "luna": [0.1, 0.3, 0.2, 0.6, 0.4, 0.9, 1.1]}
AGG = {"gpt-5.6-sol": [1000, 500, 300, 12, 1.23, True, 3],
       "gpt-6-astra": [800, 400, 200, 9, 0.87, True, 2],
       "gpt-reserve": [100, 50, 10, 2, 0.0, False, 1]}
AGG_MANY = {**AGG,
            "gpt-5.6-luna": [600, 300, 90, 7, 0.31, True, 2],
            "gpt-5.6-terra": [300, 120, 60, 4, 0.12, True, 1],
            "codex-auto-review": [200, 100, 20, 3, 0.0, False, 1],
            "long-model-name-here": [50, 20, 5, 1, 0.01, True, 1]}

# 终端“显示像素”光栅：半块 = (列-1, (行-2)*2)，图形协议 = 真实像素
RASTERS = [(109, 72), (119, 76), (159, 88), (239, 156), (1200, 700)]

PALETTE = {"蓝": (78, 121, 167), "橙": (242, 142, 43), "红": (225, 87, 89)}

CHARTS = {
    "pie": lambda: imgcharts.chart_pie(AGG, "cost"),
    "bar": lambda: imgcharts.chart_bar(LABELS, {"成本(USD)": [1.0, 2.0, 0.5, 3.0, 2.2, 1.8, 4.0]},
                                       False, "每天成本(USD)"),
    "bar-stacked": lambda: imgcharts.chart_bar(LABELS, SERIES, True, "每天成本(USD)·堆叠"),
    "area": lambda: imgcharts.chart_series("area", LABELS, SERIES, "每天成本(USD)·按模型"),
    "line": lambda: imgcharts.chart_series("line", LABELS, {"成本(USD)": [1.0, 2.0, 0.5, 3.0, 2.2, 1.8, 4.0]},
                                           "每天成本(USD)"),}


_ORIG_TARGET_PX = imgcharts._target_px


@pytest.fixture(autouse=True)
def _reset_cache():
    """_target_px / describe 是进程级缓存，每个用例前后清掉；并撤销用例内的替换。"""
    _ORIG_TARGET_PX.cache_clear()
    imgcharts.describe.cache_clear()
    yield
    imgcharts._target_px = _ORIG_TARGET_PX
    _ORIG_TARGET_PX.cache_clear()
    imgcharts.describe.cache_clear()


def test_ascii_text_rewrites_labels():
    """字符画标签转写：plotext 按 1 列=1 字符排版，中文会错位，必须转成 ASCII。"""
    from codex_usage.render import charts

    assert charts.ascii_text("各模型成本(USD)") == "by model cost (USD)"
    assert charts.ascii_text("每天成本(USD)·堆叠") == "per day cost (USD) [stacked]"
    assert charts.ascii_text("成本(USD) 分布") == "cost (USD) share"
    for label in charts.METRIC_LABEL.values():
        assert charts.ascii_text(label).isascii() and charts.ascii_text(label)
    for m in charts.METRICS:
        assert charts.ascii_text(f"每天{charts.METRIC_LABEL[m]}·按模型").isascii()


@pytest.mark.parametrize("name", ["pie", "bar", "bar-stacked", "area", "line"])
def test_text_charts_have_no_cjk(name, monkeypatch):
    """字符画档位：标题/图例/标签都不得含 CJK（否则 plotext 输出错位乱码）。"""
    from codex_usage.render import charts

    monkeypatch.setattr(charts.shutil, "get_terminal_size",
                        lambda *a, **k: os.terminal_size((120, 44)))
    build = {
        "pie": lambda: charts.chart_pie(AGG, "cost"),
        "bar": lambda: charts.chart_bar(LABELS, {"成本(USD)": [1.0, 2.0, 0.5, 3.0, 2.2, 1.8, 4.0]},
                                        False, "每天成本(USD)"),
        "bar-stacked": lambda: charts.chart_bar(LABELS, SERIES, True, "每天成本(USD)·堆叠"),
        "area": lambda: charts.chart_series("area", LABELS, SERIES, "每天成本(USD)·按模型"),
        "line": lambda: charts.chart_series("line", LABELS, SERIES, "每天成本(USD)·按模型"),
    }[name]
    out = build()
    assert out and out.strip()
    cjk = [ch for ch in out if "\u3400" <= ch <= "\u9fff" or "\uff00" <= ch <= "\uffef"]
    assert not cjk, f"{name} 字符画里仍有宽字符: {''.join(cjk[:8])}"


@pytest.mark.parametrize("mode,expect", [("tgp", "TGPImage"), ("sixel", "SixelImage"),
                                         ("halfcell", "HalfcellImage"), ("ascii", "UnicodeImage")])
def test_image_mode_override(monkeypatch, mode, expect):
    """CODEX_USAGE_IMAGE_MODE 能强制渲染类（textual-image 的类都叫 Image，必须按对象身份比）。"""
    monkeypatch.setenv("CODEX_USAGE_IMAGE_MODE", mode)
    renderable = imgcharts._renderable()
    assert imgcharts.image_mode() == mode
    assert imgcharts.image_class() is getattr(renderable, expect)


def test_image_mode_invalid_falls_back_to_auto(monkeypatch):
    monkeypatch.setenv("CODEX_USAGE_IMAGE_MODE", "  SIXEL-please  ")
    assert imgcharts.image_mode() == "auto"
    monkeypatch.delenv("CODEX_USAGE_IMAGE_MODE", raising=False)
    assert imgcharts.image_mode() == "auto"
    assert imgcharts.image_class() is imgcharts._renderable().Image


@pytest.mark.parametrize("mode,expect_half", [("auto", None), ("halfcell", True),
                                              ("tgp", False), ("ascii", None)])
def test_target_px_follows_mode(monkeypatch, mode, expect_half):
    """光栅要跟随档位：半块 = 每格 1 像素宽 2 像素高，字符回退 = 1 字符 1 像素。"""
    monkeypatch.setenv("CODEX_USAGE_IMAGE_MODE", mode)
    imgcharts._target_px.cache_clear()
    monkeypatch.setattr(imgcharts.shutil, "get_terminal_size",
                        lambda *a, **k: os.terminal_size((120, 44)))
    px_w, px_h = imgcharts._target_px()
    if expect_half is True:
        assert (px_w, px_h) == (119, 84)          # cols-1, (lines-2)*2
    elif expect_half is False:
        assert px_w > 200 and px_h > 100          # 图形协议：按格子像素放大
    else:
        assert px_h <= 44                          # 字符回退/默认：不超过行数


def test_describe_reports_mode(monkeypatch):
    monkeypatch.setenv("CODEX_USAGE_IMAGE_MODE", "halfcell")
    imgcharts.describe.cache_clear()
    d = imgcharts.describe()
    assert d["mode"] == "halfcell"
    assert d["display"] == "彩色半块"
    assert d["detected"]                                    # 自动探测结果仍要保留
    monkeypatch.delenv("CODEX_USAGE_IMAGE_MODE", raising=False)
    imgcharts.describe.cache_clear()
    assert imgcharts.describe()["mode"] == "auto"


@pytest.fixture
def png(monkeypatch):
    """_render 换成“出 PNG 并返回 PIL 图”，便于按像素检查。"""
    monkeypatch.setattr(imgcharts, "_target_px", lambda: (1200, 700))

    def capture(fig):
        buf = io.BytesIO()
        fig.canvas.print_png(buf)
        buf.seek(0)
        return Image.open(buf).convert("RGB")

    monkeypatch.setattr(imgcharts, "_render", capture)
    return capture


def test_available_and_deps():
    assert imgcharts.available() is True


def test_cjk_font_has_real_glyphs():
    """选中的字体必须真含 CJK 字形，否则中文标题会变方框。"""
    from matplotlib import font_manager, ft2font

    name = imgcharts._cjk_font()
    if name is None:
        pytest.skip("系统无 CJK 字体")
    font = ft2font.FT2Font(font_manager.findfont(font_manager.FontProperties(family=name)))
    assert font.get_char_index(ord("成")) > 0
    assert font.get_char_index(ord("本")) > 0


def test_target_px_uses_halfcell_raster(monkeypatch):
    """半块终端：图表光栅 = 格子数 × (行数×2)。"""
    import textual_image.renderable as tr
    from textual_image.renderable.halfcell import Image as HalfcellImage

    monkeypatch.setattr(imgcharts.shutil, "get_terminal_size", lambda: os.terminal_size((120, 40)))
    monkeypatch.setattr(tr, "Image", HalfcellImage)
    assert imgcharts._target_px() == (119, 76)


def test_target_px_uses_pixel_raster_for_graphics_protocol(monkeypatch):
    """图形协议终端：图表光栅 = 格子数 × 每格像素。"""
    import textual_image.renderable as tr
    from textual_image.renderable.tgp import Image as TGPImage
    import textual_image._terminal as tt

    monkeypatch.setattr(imgcharts.shutil, "get_terminal_size", lambda: os.terminal_size((120, 40)))
    monkeypatch.setattr(tr, "Image", TGPImage)
    monkeypatch.setattr(tt, "get_cell_size", lambda: (10, 20))
    assert imgcharts._target_px() == (1190, 760)


def test_charts_draw_ink_and_palette(png):
    """每类图都出真图：底图有主色像素、标题带有墨、四边无裁切。"""
    for name, build in CHARTS.items():
        img = build()
        assert img.size == (1200, 700), name
        px = img.load()
        w, h = img.size
        border = (sum(px[x, 0] != (255, 255, 255) for x in range(w))
                  + sum(px[x, h - 1] != (255, 255, 255) for x in range(w))
                  + sum(px[0, y] != (255, 255, 255) for y in range(h))
                  + sum(px[w - 1, y] != (255, 255, 255) for y in range(h)))
        assert border == 0, f"{name}: 内容被裁到边上"
        title_ink = sum(px[x, y] != (255, 255, 255)
                        for y in range(int(h * 0.09)) for x in range(w))
        assert title_ink > 0, f"{name}: 标题缺失"
        ink = {label: sum(1 for y in range(0, h, 2) for x in range(0, w, 2) if px[x, y] == color)
               for label, color in PALETTE.items()}
        assert sum(ink.values()) > 500, f"{name}: 图形没画出来 {ink}"


def test_renderable_renders_blocks():
    """textual-image renderable 经 rich 能渲染出半块/字符画。"""
    r = imgcharts.chart_bar(LABELS, SERIES, True, "每天成本(USD)·堆叠")
    console = Console(record=True, width=80, height=24, force_terminal=False)
    console.print(r)
    text = console.export_text()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert len(lines) > 3
    assert any(ch in text for ch in "▀█▓▒░")


def _overflow(fig) -> list:
    """出图后仍越出画布边界的文本/图例图元（display 坐标，y 向上）。"""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    w, h = fig.canvas.get_width_height()
    ax = fig.axes[0]
    ylo, yhi = ax.get_ylim()
    artists = [("标题", ax.title)]
    artists += [("x 标签", t) for t in ax.get_xticklabels()]
    artists += [("y 标签", t) for t in ax.get_yticklabels()
                if ylo - 1e-9 <= t.get_position()[1] <= yhi + 1e-9]   # 轴范围外的占位刻度不绘制
    artists += [("图例", lg) for lg in (ax.get_legend(), *fig.legends) if lg is not None]
    bad = []
    for label, artist in artists:
        bb = artist.get_window_extent(renderer)
        if bb.x0 < -0.5 or bb.x1 > w + 0.5 or bb.y0 < -0.5 or bb.y1 > h + 0.5:
            text = artist.get_text() if hasattr(artist, "get_text") else ""
            bad.append((label, text, tuple(round(v) for v in bb.extents), (w, h)))
    return bad


@pytest.mark.parametrize("px", RASTERS)
def test_no_artist_overflow_at_real_rasters(monkeypatch, px):
    """真实终端光栅（含半块 110×38 档）下，标题/刻度/图例都不得越出画布。

    回归点：只在 1200×700 光栅上验证过，半块档下图例右溢、旋转标签下溢、标题超宽全漏掉了。
    """
    monkeypatch.setattr(imgcharts, "_target_px", lambda: px)
    saved = {}
    monkeypatch.setattr(imgcharts, "_render", lambda fig: saved.setdefault("fig", fig))
    cases = {
        "pie-多模型": lambda: imgcharts.chart_pie(AGG_MANY, "cost"),
        "bar-7天": lambda: imgcharts.chart_bar(LABELS, {"成本(USD)": SERIES["sol"]}, False, "每天成本(USD)"),
        "bar-20天": lambda: imgcharts.chart_bar(DAYS20, {"成本(USD)": [1.0 + i % 4 for i in range(20)]},
                                                False, "每天成本(USD)"),
        "bar-堆叠": lambda: imgcharts.chart_bar(LABELS, SERIES, True, "每天成本(USD)·堆叠"),
        "line-多序列": lambda: imgcharts.chart_series("line", LABELS, SERIES, "每天成本(USD)·按模型"),
        "area-20天": lambda: imgcharts.chart_series("area", DAYS20,
                                                    {"成本(USD)": [1.0 + i % 4 for i in range(20)]},
                                                    "每天成本(USD)"),
    }
    for name, build in cases.items():
        saved.clear()
        build()
        bad = _overflow(saved["fig"])
        assert not bad, f"{name} @ {px}: 图元越出画布 {bad[:2]}"


@pytest.mark.parametrize("px", [(20, 4), (40, 20), (79, 22), (2400, 1600)])
def test_extreme_raster_does_not_crash(monkeypatch, px):
    """极小/极大终端光栅下边距要能收敛（曾因 bottom >= top 直接抛 ValueError）。"""
    monkeypatch.setattr(imgcharts, "_target_px", lambda: px)
    assert imgcharts.chart_bar(LABELS[:2], {"成本(USD)": [1.0, 2.0]}, False, "每天成本(USD)") is not None
    assert imgcharts.chart_bar(LABELS[:2], {k: v[:2] for k, v in SERIES.items()}, True, "堆叠") is not None
    assert imgcharts.chart_series("line", LABELS[:2], {"成本(USD)": [1.0, 2.0]}, "每天成本(USD)") is not None
    assert imgcharts.chart_pie(AGG, "cost") is not None


def test_empty_data_returns_hint():
    assert imgcharts.chart_bar(LABELS, {}, False, "x") == "(无数据可画)"
    assert imgcharts.chart_series("line", LABELS, {}, "x") == "(无数据可画)"
    assert imgcharts.chart_pie({"m": [0, 0, 0, 0, 0.0, True, 1]}, "cost") == "(无数据可画)"
