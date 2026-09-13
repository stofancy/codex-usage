"""自描述与自检：帮助入口、--schema 契约、--doctor 诊断。"""

import json
import os
import subprocess
import sys

import pytest

from codex_usage import selfdoc
from codex_usage.cli import build_parser

MOD = "codex_usage.cli"


def run(*args):
    return subprocess.run([sys.executable, "-m", MOD, *args], capture_output=True, text=True, env=None)


@pytest.mark.parametrize("flag", ["--help", "-h", "/?", "-?", "help"])
def test_help_entry_points(flag):
    """人读帮助的各个入口都要可用，且包含示例/语义/退出码/数据源四段。"""
    r = run(flag)
    assert r.returncode == 0, r.stderr[-200:]
    assert "usage: codex-usage" in r.stdout
    for section in ("示例:", "语义约定:", "输出与退出码:", "数据源与环境变量:"):
        assert section in r.stdout


def test_schema_covers_every_option():
    """schema 的选项清单必须与 argparse 定义一致，避免自描述落后于实现。"""
    parser = build_parser()
    schema = selfdoc.schema(parser)
    declared = {f for o in schema["options"] for f in o["flags"]}
    actual = {f for a in parser._actions for f in a.option_strings}
    assert declared == actual
    json.dumps(schema, ensure_ascii=False)          # 必须可 JSON 序列化（Agent 要解析）
    assert schema["schema_version"] >= 1 and schema["version"]
    assert {"0", "1", "141"} <= set(schema["exit_codes"])
    assert schema["examples"] and schema["enums"]["chart"] == ["pie", "bar", "area", "line"]


def test_schema_fields_match_real_json_output(env):
    """schema 声明的 JSON 字段与真实 --json 输出对账（防契约漂移）。"""
    r = run("--json", "--since", "2026-09-10", "--until", "2026-09-11")
    assert r.returncode == 0, r.stderr[-300:]
    records = [json.loads(line) for line in r.stdout.splitlines() if line.strip()]
    assert records
    fields = selfdoc.schema(build_parser())["json_output"]
    assert set(records[0]) == set(fields["fields"])
    model = records[0]["models"]
    assert model, "夹具里应有按模型明细"
    assert set(next(iter(model.values()))) == set(fields["model_fields"])


def test_schema_cli_output(env):
    r = run("--schema")
    assert r.returncode == 0
    d = json.loads(r.stdout)
    assert d["name"] == "codex-usage"
    assert any("--chart" in o["flags"] for o in d["options"])


def test_doctor_reports_environment(env):
    d = selfdoc.doctor()
    assert d["version"] and d["python"] and d["executable"]
    assert d["data"]["sessions_dir"]["exists"] is True
    assert d["data"]["sessions_dir"]["rollout_files"] > 0
    assert d["data"]["pricing_file"]["models"] >= 10     # 合并后（内置表作基底）
    assert "env-file" in d["data"]["pricing_file"]["source"]   # 夹具的自定义表覆盖生效
    assert d["render"]["tier"]
    assert d["render"]["mode"] in ("auto", "tgp", "sixel", "halfcell", "ascii")
    assert "detected" in d["render"]                     # 自动探测结果保留（无 image extras 时为 None）
    text = selfdoc.format_doctor(d)
    for section in ("会话数据", "归档数据", "定价", "图表渲染", "中文字体"):
        assert section in text
    # CI 上没有中文字体，doctor 会给出字体提示：除它以外不该有告警
    assert not [h for h in d["hints"] if "中文字体" not in h], d["hints"]


def test_doctor_reports_missing_sources(monkeypatch, tmp_path):
    """会话目录缺失是真问题；自定义定价文件无效则回退内置表（说明而非告警）。"""
    monkeypatch.setenv("CODEX_USAGE_SESSIONS_DIR", str(tmp_path / "nope"))
    monkeypatch.setenv("CODEX_USAGE_PRICING_FILE", str(tmp_path / "nope.json"))
    d = selfdoc.doctor()
    assert d["ok"] is False
    hints = " ".join(d["hints"])
    assert "会话目录不存在" in hints
    assert "定价不可用" not in hints                      # 内置表兜底，不该报错
    assert d["data"]["pricing_file"]["models"] >= 10      # 内置表确实带价
    assert d["data"]["pricing_file"]["source"] != "env-file"
    assert any("自定义定价文件不可用" in n for n in d["notes"])
    assert "需要注意:" in selfdoc.format_doctor(d)


def test_doctor_when_pricing_fully_unavailable(monkeypatch):
    """三层定价都读不到时才算问题，提示要指向 --update-pricing。"""
    from codex_usage import pricing

    monkeypatch.setattr(pricing, "load_pricing", lambda *a, **k: {})
    monkeypatch.setattr(pricing, "source_info",
                        lambda: {"source": "builtin", "path": None, "models": 0, "updated": None})
    d = selfdoc.doctor()
    assert any("定价不可用" in h and "--update-pricing" in h for h in d["hints"])


def test_schema_documents_image_mode():
    """档位开关要能被 Agent 从 --schema 里发现。"""
    env = selfdoc.schema(build_parser())["chart_rendering"]["env"]
    assert "CODEX_USAGE_IMAGE_MODE" in env
    assert "halfcell" in env["CODEX_USAGE_IMAGE_MODE"]


def test_doctor_cli_json(env):
    r = run("--doctor", "--json")
    assert r.returncode == 0
    d = json.loads(r.stdout)
    assert d["data"]["sessions_dir"]["rollout_files"] > 0
    assert "hints" in d


@pytest.mark.skipif(os.name != "posix", reason="需要 pty")
def test_doctor_json_clean_under_pty(env):
    """真实终端（pty）下自检 JSON 也必须可直接解析：终端探测序列走 stderr，别污染 stdout。"""
    import fcntl
    import pty
    import struct
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 110, 0, 0))
    child_env = {**os.environ, "TERM": "xterm-256color", "COLUMNS": "110", "LINES": "40"}
    proc = subprocess.Popen([sys.executable, "-m", MOD, "--doctor", "--json"],
                            stdin=slave, stdout=slave, stderr=subprocess.PIPE, env=child_env)
    os.close(slave)
    out = b""
    while True:
        try:
            chunk = os.read(master, 65536)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    os.close(master)
    proc.wait()
    stderr = proc.stderr.read().decode("utf-8", "replace")
    report = json.loads(out.decode("utf-8", "replace").replace("\r\n", "\n"))
    assert report["render"]["stdout_is_tty"] is True
    assert report["render"]["tier"]
    assert "\x1b" in stderr or stderr == ""      # 探测序列被引到 stderr（若发生）
