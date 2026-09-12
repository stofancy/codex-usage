"""CLI 端到端测试：子进程调用，覆盖视图、聚合语义、图表、JSON、容错。"""

import json
import subprocess
import sys
from datetime import datetime

import pytest

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
    """从 rich 表格提取最后的 合计/总计 行 token 数。"""
    import re
    nums = None
    for line in out.splitlines():
        if ("合计" in line or "总计" in line) and "$" in line:
            m = re.search(r"([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+\$[\d,]+\.\d+\*?\s*$", line)
            if m:
                nums = tuple(int(x.replace(",", "")) for x in m.groups())
    return nums


def test_by_model_aggregation_semantics(env):
    r = run(env, "--by-model")
    assert r.returncode == 0
    head = r.stdout.splitlines()[:3]
    assert any("会话数" in l for l in head)          # 聚合表表头
    assert not any("时间" in l for l in head)         # 无会话明细列
    import re
    ids = re.findall(r"[0-9a-f]{8}-[0-9a-f]{4}", r.stdout)
    assert not ids                                   # 聚合表无会话 ID
    rj = run(env, "--json")
    models = set()
    for ln in rj.stdout.splitlines():
        models |= set(json.loads(ln)["models"])
    rows = [l for l in r.stdout.splitlines() if l.strip().startswith(("gpt-",))]
    assert len(rows) == len(models)


def test_unpriced_model_counted(env):
    r = run(env, "--since", "2026-09-11", "--until", "2026-09-11")
    assert r.returncode == 0
    assert "gpt-mystery" in r.stdout
    assert "$0.00*" in r.stdout
    assert "无定价" in r.stdout


def test_json_output(env):
    r = run(env, "--json")
    lines = [json.loads(l) for l in r.stdout.splitlines()]
    assert lines
    for d in lines:
        assert {"session_id", "models", "input_net", "cost_usd_known"} <= set(d)
        for m, v in d["models"].items():
            assert {"input_gross", "cached", "output", "reasoning"} <= set(v)


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


def test_chart_family_conflict(env):
    r = run(env, "--chart", "pie", "--family")
    assert r.returncode != 0
    assert "不组合" in (r.stderr + r.stdout)


def test_empty_range(env):
    r = run(env, "--since", "2026-08-01", "--until", "2026-08-02")
    assert r.returncode == 0
    assert "没有会话" in r.stdout
