"""终端图表：饼图(termcharts)、柱状/堆叠柱/面积/折线(plotext 5.x，6.x 有渲染 bug 勿升)。

图表只作用于聚合维度：饼图=按模型，柱状=天/模型/天×模型(堆叠)，面积与折线=按天趋势。
"""

import shutil

import plotext as plt
from termcharts import pie as tc_pie

METRICS = ("cost", "input", "cache", "output", "total")
METRIC_LABEL = {"cost": "成本(USD)", "input": "净输入", "cache": "缓存读",
                "output": "输出", "total": "总 tokens"}


def metric_of(entry: list, metric: str) -> float:
    """从聚合槽位 [net, cached, out, calls, cost, known, nsess] 取指标值。"""
    net, cached, out, cost = entry[0], entry[1], entry[2], entry[4]
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
    return tc_pie(data, title=f"{METRIC_LABEL[metric]} 分布")


def chart_bar(labels: list[str], series: dict[str, list], stacked: bool, title: str) -> str:
    plt.clear_figure()
    _plot_size()
    plt.title(title)
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
    plt.title(title)
    if not series:
        return "(无数据可画)"
    for name, vals in series.items():
        plt.plot(vals, label=name, fillx=(kind == "area"))
    plt.xticks(range(len(day_labels)), day_labels)
    return _build()
