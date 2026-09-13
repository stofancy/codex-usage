"""测试夹具：合成 rollout 会话文件 + 定价表，通过环境变量注入路径。"""

import json
import os
import uuid
from datetime import datetime, timezone

import pytest


def utc_at(y: int, mo: int, d: int, h: int, mi: int = 0) -> str:
    """按**本机时区**给出这些墙上时间，转成 rollout 里的 UTC 时间戳。

    rollout 的 `timestamp` 是 UTC，而 `--since/--until` 与统计都按本地时区解释，
    因此夹具不能硬编码 UTC：在 UTC 的 CI 里，硬编码会让"本地 09:00 的会话"
    落到窗口之外，测试随运行环境时区飘红。
    """
    wall = datetime(y, mo, d, h, mi, tzinfo=datetime.now().astimezone().tzinfo)
    return wall.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


T0 = utc_at(2026, 9, 10, 10, 0)    # 本地 10:00
T1 = utc_at(2026, 9, 10, 11, 30)   # 本地 11:30
T2 = utc_at(2026, 9, 11, 9, 0)     # 本地 09:00
T3 = utc_at(2026, 9, 11, 14, 0)    # 本地 14:00
ARCH = utc_at(2026, 9, 9, 8, 0)    # 归档会话：本地 09-09 08:00

PRICE = {"models": [
    {"modelId": "gpt-5.6-luna", "displayName": "Luna",
     "inputCostPerMillion": "10", "outputCostPerMillion": "50", "cacheReadCostPerMillion": "1"},
    {"modelId": "gpt-5.6-sol", "displayName": "Sol",
     "inputCostPerMillion": "20", "outputCostPerMillion": "60", "cacheReadCostPerMillion": "2"},
]}


def line(ts, typ, payload):
    return json.dumps({"timestamp": ts, "type": typ, "payload": payload})


def token_event(ts, last, total=None):
    info = {"last_token_usage": last, "total_token_usage": total or last}
    return line(ts, "event_msg", {"type": "token_count", "info": info})


def meta_event(ts, sid, thread_source="user", source="vscode", spawn=None):
    src = {"subagent": {"thread_spawn": spawn}} if spawn else source
    payload = {"session_id": sid, "id": sid, "cwd": "/tmp/proj", "originator": "Codex Desktop",
               "source": src, "thread_source": thread_source, "model_provider": "openai"}
    return line(ts, "session_meta", payload)


def turn_event(ts, model):
    return line(ts, "turn_context", {"model": model})


def usage(in_, cached, out):
    return {"input_tokens": in_, "cached_input_tokens": cached, "output_tokens": out,
            "reasoning_output_tokens": out // 2}


def write_rollout(dir_path, local_ts, sid, body_lines):
    """按本地时间生成标准 rollout 文件名。"""
    d = local_ts.strftime("%Y-%m-%dT%H-%M-%S")
    fname = f"rollout-{d}-{sid}.jsonl"
    path = os.path.join(dir_path, fname)
    os.makedirs(dir_path, exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(body_lines) + "\n")
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    """构建合成数据环境：2 天、多会话、含子代理/分页/无定价模型，返回路径与期望值。"""
    sess = tmp_path / "sessions"
    arch = tmp_path / "archived_sessions"
    price = tmp_path / "model-pricing.json"
    price.write_text(json.dumps(PRICE))

    ids = {k: str(uuid.uuid4()) for k in ("A", "B", "C", "child", "page", "arch")}

    # 会话 A: user, 09-10 本地 10:00, luna 两轮 (净1000/缓存5000/出300 + 净2000/缓存20000/出700)
    write_rollout(str(sess / "2026" / "09" / "10"), __import__("datetime").datetime(2026, 9, 10, 10, 0, 0),
                  ids["A"], [
        meta_event(T0, ids["A"]),
        turn_event(T0, "gpt-5.6-luna"),
        token_event(T0, usage(6000, 5000, 300), usage(6000, 5000, 300)),
        token_event(T1, usage(22000, 20000, 700), usage(28000, 25000, 1000)),
    ])
    # 会话 B: subagent (thread_spawn -> A), 09-10 11:30, sol 一轮
    write_rollout(str(sess / "2026" / "09" / "10"), __import__("datetime").datetime(2026, 9, 10, 11, 30, 0),
                  ids["B"], [
        meta_event(T1, ids["A"], thread_source="subagent",
                   spawn={"parent_thread_id": ids["A"], "depth": 1,
                          "agent_nickname": "Feynman", "agent_role": "sol_analyst"}),
        turn_event(T1, "gpt-5.6-sol"),
        token_event(T1, usage(8500, 8000, 100), usage(8500, 8000, 100)),
    ])
    # 会话 C: user 双 UUID 文件名（父_子），09-11 09:00，含无定价模型 gpt-mystery
    p = sess / "2026" / "09" / "11"
    p.mkdir(parents=True, exist_ok=True)
    fname = f"rollout-2026-09-11T09-00-00-{ids['C']}_{ids['child']}.jsonl"
    (p / fname).write_text("\n".join([
        meta_event(T2, ids["C"]),
        turn_event(T2, "gpt-mystery"),
        token_event(T2, usage(1300, 1000, 50), usage(1300, 1000, 50)),
    ]) + "\n")
    # 分页: 同一线程 page 两个文件 (thread_source=user, 双 uuid 文件名, 同首 uuid)
    for i, ts in enumerate([T2, T3]):
        fn = f"rollout-2026-09-11T0{9+i}-00-00-{ids['page']}_{uuid.uuid4()}.jsonl"
        (p / fn).write_text("\n".join([
            meta_event(ts, ids["page"]),
            turn_event(ts, "gpt-5.6-luna"),
            token_event(ts, usage(2100 + i * 10, 2000, 30 + i), usage(2100 + i * 10, 2000, 30 + i)),
        ]) + "\n")
    # 归档会话
    write_rollout(str(arch), __import__("datetime").datetime(2026, 9, 9, 8, 0, 0),
                  ids["arch"], [
        meta_event(ARCH, ids["arch"]),
        turn_event(ARCH, "gpt-5.6-sol"),
        token_event(ARCH, usage(550, 500, 10), usage(550, 500, 10)),
    ])

    monkeypatch.setenv("CODEX_USAGE_SESSIONS_DIR", str(sess))
    monkeypatch.setenv("CODEX_USAGE_ARCHIVE_DIR", str(arch))
    monkeypatch.setenv("CODEX_USAGE_PRICING_FILE", str(price))
    return {"sessions": str(sess), "archive": str(arch), "pricing": str(price), "ids": ids}
