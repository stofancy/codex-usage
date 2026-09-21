"""终端图表：饼图(termcharts)、柱状/堆叠柱/面积/折线(plotext 5.x，6.x 有渲染 bug 勿升)。

图表只作用于聚合维度：饼图=按模型，柱状=天/模型/天×模型(堆叠)，面积与折线=按天趋势。

字符画渲染器（plotext/termcharts）按 1 列 = 1 字符排版，遇到中文这类宽字符会错位，
于是这里统一把标题与图例转写成 ASCII：真图路径（matplotlib）仍用中文，只有字符画兜底时转写。
"""

import shutil

import plotext as plt
from termcharts import pie as tc_pie

METRICS = ("cost", "input", "cache", "hit", "output", "total", "per_mtok")
METRIC_LABEL = {"cost": "成本(USD)", "input": "净输入", "cache": "缓存读",
                "hit": "缓存命中率", "output": "输出", "total": "总 tokens",
                "per_mtok": "每百万 tokens(USD)"}
# 比率/单位价指标不能做“占总量的份额”，饼图直接拒绝
PIE_UNSUPPORTED = ("hit", "per_mtok")

# 字符画用的 ASCII 词表（长词在前，避免部分覆盖）
_ASCII_WORDS = (
    ("·按模型", " by model"),
    ("·堆叠", " [stacked]"),
    (" 分布", " share"),
    ("每天", "per day "),
    ("各模型", "by model "),
    ("成本(USD)", "cost (USD)"),
    ("每百万 tokens(USD)", "per 1M tokens (USD)"),
    ("缓存命中率", "cache hit rate"),
    ("净输入", "input"),
    ("缓存读", "cache read"),
    ("输出", "output"),
    ("总 tokens", "total tokens"),
)


def ascii_text(s: str) -> str:
    """把图表标签转写成纯 ASCII（字符画渲染器不支持宽字符，中文会错位）。"""
    for zh, en in _ASCII_WORDS:
        s = s.replace(zh, en)
    return "".join(ch for ch in s if 32 <= ord(ch) < 127).strip()


def metric_of(entry: list, metric: str) -> float:
    """从聚合槽位 [net, cached, out, calls, cost, known, nsess] 取指标值。

    ``hit`` 是**加权**命中率：Σ缓存读 / Σ毛输入（毛输入 = Σ净 + Σ缓存读）。它对
    聚合后的槽位计算，所以按天/按模型/家族分组都不会退化成“平均百分比”。
    """
    net, cached, out, cost = entry[0], entry[1], entry[2], entry[4]
    if metric == "hit":
        gross = net + cached
        return cached / gross if gross else 0.0
    if metric == "per_mtok":
        total = net + cached + out
        return cost / total * 1_000_000 if total else 0.0
    return {"cost": cost, "input": net, "cache": cached,
            "output": out, "total": net + cached + out}[metric]


def _plot_size(w=110, h=18):
    cols = shutil.get_terminal_size().columns
    plt.plot_size(max(40, min(w, cols - 2)), h)


def _build() -> str:
    s = plt.build()
    plt.clear_figure()
    return s


def chart_pie(model_agg: dict[str, list], metric: str) -> str:
    data = {}
    for m, a in model_agg.items():
        v = round(metric_of(a, metric), 4)
        if v:
            data[m] = v
    if not data:
        return "(无数据可画)"
    return tc_pie(data, title=ascii_text(f"{METRIC_LABEL[metric]} 分布"))


def chart_bar(labels: list[str], series: dict[str, list], stacked: bool, title: str) -> str:
    plt.clear_figure()
    _plot_size()
    plt.title(ascii_text(title))
    labels = [ascii_text(x) for x in labels]
    series = {ascii_text(k): v for k, v in series.items()}
    if not series:
        return "(无数据可画)"
    if len(series) == 1:
        name, vals = next(iter(series.items()))
        plt.bar(labels, vals, label=name)
    elif stacked:
        plt.stacked_bar(labels, list(series.values()), label=list(series))
    else:
        plt.multiple_bar(labels, list(series.values()), label=list(series))
    return _build()


def chart_series(kind: str, day_labels: list[str], series: dict[str, list], title: str) -> str:
    plt.clear_figure()
    _plot_size(h=16)
    plt.title(ascii_text(title))
    day_labels = [ascii_text(x) for x in day_labels]
    series = {ascii_text(k): v for k, v in series.items()}
    if not series:
        return "(无数据可画)"
    for name, vals in series.items():
        plt.plot(vals, label=name, fillx=(kind == "area"))
    plt.xticks(range(len(day_labels)), day_labels)
    return _build()
