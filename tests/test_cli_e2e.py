"""CLI 端到端测试：子进程调用，覆盖视图、聚合语义、图表、JSON、容错。"""

import json
import subprocess
import sys
from datetime import datetime


MOD = "codex_usage.cli"


def run(env, *args, code="2026-09-10", until="2026-09-11"):
    return subprocess.run(
        [sys.executable, "-m", MOD, "--since", code, "--until", until, *args],
        capture_output=True, text=True, env=None)


def test_views_no_crash_and_totals(env):
    base = None
    for combo in ([], ["--raw"], ["--family"], ["--by-model"], ["--family", "--by-model"],
                  ["--by-day"], ["--by-day", "--by-model"], ["--by-day", "--family"],
                  ["--by-day", "--family", "--by-model"], ["--raw", "--by-model"]):
        r = run(env, *combo)
        assert r.returncode == 0, f"{combo}: {r.stderr[-400:]}"
        assert "Traceback" not in r.stderr
        nums = _grand_totals(r.stdout)
        assert nums is not None, f"{combo}: 无总计行"
        if base is None:
            base = nums
        assert nums == base, f"{combo}: 合计不一致 {nums} != {base}"


def _grand_totals(out: str):
    """从 rich 表格提取最后的 合计/总计 行末 7 个数值 token（净/缓/输/总/调/单次/成本）。"""
    import re
    nums = None
    for line in out.splitlines():
        if ("合计" in line or "总计" in line) and "$" in line:
            toks = re.findall(r"\$[\d,.]+\*?|-|\d[\d,]*", line)
            if len(toks) >= 7:
                nums = tuple(toks[-7:])
    return nums


def test_by_model_aggregation_semantics(env):
    r = run(env, "--by-model")
    assert r.returncode == 0
    head = r.stdout.splitlines()[:3]
    assert any("会话数" in line for line in head)          # 聚合表表头
    assert not any("时间" in line for line in head)         # 无会话明细列
    import re
    ids = re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}", r.stdout)
    assert not ids                                   # 聚合表无会话 ID
    rj = run(env, "--json")
    models = set()
    for ln in rj.stdout.splitlines():
        models |= set(json.loads(ln)["models"])
    rows = [line for line in r.stdout.splitlines() if line.strip().startswith(("gpt-",))]
    assert len(rows) == len(models)


def test_unpriced_model_counted(env):
    r = run(env, "--since", "2026-09-11", "--until", "2026-09-11")
    assert r.returncode == 0
    assert "gpt-mystery" in r.stdout
    assert "$0.00*" in r.stdout
    assert "无定价" in r.stdout


def test_json_output(env):
    r = run(env, "--json")
    lines = [json.loads(line) for line in r.stdout.splitlines()]
    assert lines
    for d in lines:
        assert {"session_id", "models", "input_net", "cost_usd_known",
                "calls", "total_tokens"} <= set(d)
        # 数值口径：总 = 净 + 缓存 + 输出；调用次数非零
        assert d["total_tokens"] == d["input_net"] + d["cache_read"] + d["output"]
        assert d["calls"] >= 1
        for m, v in d["models"].items():
            assert {"input_gross", "cached", "output", "reasoning", "calls"} <= set(v)
            assert v["input_gross"] >= v["cached"] and v["calls"] >= 1


def test_model_metric_total_counts_cache_once():
    """--metric total 的按模型路径：total = 毛输入 + 输出，缓存读只能计一次。

    回归点：曾用 sum(v[:3])（毛输入已含缓存）导致 total 虚高。
    """
    from codex_usage import cli
    from codex_usage.render import charts

    v = [6000, 5000, 300, 150, 2]                       # 毛 6000（含缓存 5000）、出 300
    entry = [v[0] - v[1], v[1], v[2], 0, 0.0, True, 1]  # aggregate_models 槽位
    assert cli._model_metric("m", v, "input", {}) == 1000
    assert cli._model_metric("m", v, "cache", {}) == 5000
    assert cli._model_metric("m", v, "output", {}) == 300
    assert cli._model_metric("m", v, "total", {}) == 6300
    for metric in ("input", "cache", "output", "total"):
        assert cli._model_metric("m", v, metric, {}) == charts.metric_of(entry, metric)


def test_new_metric_columns_and_alignment(env):
    """总 tokens/调用/单次成本 列存在，且合计行数字与数据行同列右对齐。

    位置按终端显示宽计算（rich 输出含 CJK，字符索引≠显示列）。
    """
    import re
    import unicodedata
    r = run(env, "--by-model")
    assert r.returncode == 0
    for head in ("总 tokens", "调用", "单次成本"):
        assert head in r.stdout
    lines = [line.rstrip() for line in r.stdout.splitlines() if line.strip()]
    data = next(line for line in lines if line.strip().startswith("gpt-"))
    total = next(line for line in lines if "合计" in line and "$" in line)

    def display_col(line: str, idx: int) -> int:
        return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in line[:idx])

    def tail_spans(line):
        # 行尾 7 个数值 token 的显示列 (start, end)：数字列全部右对齐
        return [(display_col(line, m.start()), display_col(line, m.end())) for m in
                re.finditer(r"\$[\d,.]+\*?|-|\d[\d,]*", line)][-7:]

    ds, ts = tail_spans(data), tail_spans(total)
    assert len(ds) == len(ts) == 7
    assert [e for _, e in ds] == [e for _, e in ts]   # 各列右边缘逐列对齐


def test_compact_time_args(env):
    """紧凑时间与等价显式格式给出相同结果；--until 缺省部分补满。"""
    r1 = run(env, "--since", "2026-09-11", "--until", "2026-09-11")
    r2 = run(env, "--since", "20260911", "--until", "20260911")
    assert r2.returncode == 0 and r2.stdout == r1.stdout
    # 20260911-14 作为 until → 当天 14:59:59，覆盖 14:00 的分页第二页
    r3 = run(env, "--since", "20260911", "--until", "20260911-14")
    assert r3.returncode == 0
    assert "09-11" in r3.stdout
    # 分钟级紧凑格式与显式格式等价
    r4 = run(env, "--since", "20260911-09", "--until", "20260911-10")
    r5 = run(env, "--since", "2026-09-11 09:00", "--until", "2026-09-11 10:59:59")
    assert r4.returncode == 0 and r4.stdout == r5.stdout


def test_filters(env):
    r = run(env, "--type", "subagent")
    assert "Feynman" in r.stdout
    r = run(env, "--model", "gpt-5.6-sol")
    assert "gpt-5.6-sol" in r.stdout
    # --model 行级过滤：数据区不出现其他模型，也不再有混合标记
    data_part = r.stdout.split("合计")[0]
    assert "gpt-5.6-luna" not in data_part
    assert "+mix" not in r.stdout


def test_single_dash_tolerance(env):
    r = run(env, "-by-model")
    assert r.returncode == 0
    assert "已按 '--by-model' 处理" in r.stderr


def test_charts(env):
    for chart in ("pie", "bar", "area", "line"):
        r = run(env, "--chart", chart)
        assert r.returncode == 0, f"{chart}: {r.stderr[-300:]}"
        assert r.stdout.strip(), chart
    r = run(env, "--chart", "bar", "--by-day", "--by-model")
    assert r.returncode == 0
    r = run(env, "--chart", "area", "--by-model")
    assert r.returncode == 0


def test_chart_ascii_and_pipe_fallback(env):
    """--ascii 强制字符画；非 TTY（子进程 stdout 是管道）默认同样回退字符画。"""
    forced = run(env, "--chart", "bar", "--ascii")
    piped = run(env, "--chart", "bar")
    assert forced.returncode == 0 and forced.stdout.strip()
    assert piped.stdout == forced.stdout
    assert "▀" not in forced.stdout          # 半块图不会出现在字符画里
    assert "▀" not in run(env, "--chart", "pie", "--ascii").stdout
    # 字符画标签必须 ASCII 化：plotext 按 1 列=1 字符排版，中文会错位乱码
    cjk = [ch for ch in forced.stdout if "\u3400" <= ch <= "\u9fff"]
    assert not cjk, f"字符画里仍有中文: {''.join(cjk[:8])}"
    assert "cost (USD)" in forced.stdout


def test_use_image_respects_image_mode_env(monkeypatch):
    """CODEX_USAGE_IMAGE_MODE=ascii 等同 --ascii；halfcell/tgp 仍走真图路径；非法值按 auto。"""
    from codex_usage import cli
    from codex_usage.render import imgcharts

    args = cli.build_parser().parse_args(["--chart", "bar", "--by-model"])
    monkeypatch.setattr(cli.sys.stdout, "isatty", lambda: True)
    monkeypatch.setattr(imgcharts, "available", lambda: True)
    monkeypatch.delenv("CODEX_USAGE_IMAGE_MODE", raising=False)
    assert cli._use_image(args) is True
    for mode, expect in (("ascii", False), ("halfcell", True), ("tgp", True), ("bogus", True)):
        monkeypatch.setenv("CODEX_USAGE_IMAGE_MODE", mode)
        assert cli._use_image(args) is expect, mode
    monkeypatch.setenv("CODEX_USAGE_IMAGE_MODE", "halfcell")
    assert cli._use_image(cli.build_parser().parse_args(["--ascii"])) is False


def test_ascii_help_and_single_dash(env):
    r = run(env, "--help")
    assert "--ascii" in r.stdout
    r = run(env, "-ascii", "--chart", "bar")
    assert r.returncode == 0
    assert "已按 '--ascii' 处理" in r.stderr


def test_chart_family_conflict(env):
    r = run(env, "--chart", "pie", "--family")
    assert r.returncode != 0
    assert "不组合" in (r.stderr + r.stdout)


def test_chart_pie_by_day_conflict(env):
    r = run(env, "--chart", "pie", "--by-day")
    assert r.returncode != 0
    assert "饼图" in (r.stderr + r.stdout)


def test_chart_conflict_reported_without_data(env):
    """参数冲突先于数据扫描报出：空范围也要报错，而不是静默「没有会话」。"""
    r = run(env, "--since", "2026-08-01", "--until", "2026-08-02", "--chart", "pie", "--by-day")
    assert r.returncode != 0
    assert "饼图" in (r.stderr + r.stdout)
    r = run(env, "--since", "2026-08-01", "--until", "2026-08-02", "--chart", "bar", "--family")
    assert r.returncode != 0
    assert "不组合" in (r.stderr + r.stdout)


def test_chart_image_failure_falls_back_to_text(env, monkeypatch, capsys):
    """真图渲染抛异常时回退字符画并提示，不让命令以 traceback 结束。"""
    from codex_usage import cli
    from codex_usage.parser import collect
    from codex_usage.pricing import load_pricing
    from codex_usage.render import imgcharts

    recs = collect(env["sessions"], datetime(2026, 9, 10), datetime(2026, 9, 11, 23, 59, 59))
    args = cli.build_parser().parse_args(["--chart", "bar", "--by-day"])
    monkeypatch.setattr(cli, "_use_image", lambda a: True)

    def boom(*_a, **_kw):
        raise RuntimeError("模拟渲染失败")

    monkeypatch.setattr(imgcharts, "chart_bar", boom)
    cli._chart(args, recs, load_pricing(env["pricing"]))
    out = capsys.readouterr()
    assert "真图渲染失败" in out.err and "模拟渲染失败" in out.err
    assert out.out.strip()                      # 回退后的字符画有内容


def test_use_image_gate(monkeypatch, capsys):
    """真图三条回退路径：非 TTY / --ascii / 未装 image extras（并提示装法）。"""
    from codex_usage import cli

    class Args:
        ascii = False

    class ArgsAscii:
        ascii = True

    assert cli._use_image(Args()) is False                       # pytest 的 stdout 不是 TTY
    monkeypatch.setattr(cli.sys, "stdout", type("T", (), {"isatty": lambda self: True})())
    assert cli._use_image(ArgsAscii()) is False                  # --ascii 优先
    monkeypatch.setattr(cli.imgcharts, "available", lambda: True)
    assert cli._use_image(Args()) is True
    monkeypatch.setattr(cli.imgcharts, "available", lambda: False)
    assert cli._use_image(Args()) is False
    assert "uv tool install" in capsys.readouterr().err


def test_empty_range(env):
    r = run(env, "--since", "2026-08-01", "--until", "2026-08-02")
    assert r.returncode == 0
    assert "没有会话" in r.stdout
