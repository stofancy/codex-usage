"""解析器单元测试：会话 ID 规则、父子归属、分页合并、时间窗口、时间参数格式、计量口径。"""

import json
import os
from datetime import datetime

import pytest

from codex_usage.parser import collect, parse_rollout, parse_time_arg


@pytest.mark.parametrize("s,expected", [
    ("2026-09-12", datetime(2026, 9, 12)),
    ("2026-09-12 16:10", datetime(2026, 9, 12, 16, 10)),
    ("2026-09-12T16:10:23", datetime(2026, 9, 12, 16, 10, 23)),
    ("20260912", datetime(2026, 9, 12)),
    ("20260912-16", datetime(2026, 9, 12, 16, 0, 0)),
    ("20260912-1610", datetime(2026, 9, 12, 16, 10, 0)),
    ("20260912-161023", datetime(2026, 9, 12, 16, 10, 23)),
    ("20260912T161023", datetime(2026, 9, 12, 16, 10, 23)),
    ("20260912 16:10", datetime(2026, 9, 12, 16, 10, 0)),
    ("20260912-16:10:23", datetime(2026, 9, 12, 16, 10, 23)),
    ("20260912161023", datetime(2026, 9, 12, 16, 10, 23)),
])
def test_parse_time_arg_formats(s, expected):
    assert parse_time_arg(s) == expected


@pytest.mark.parametrize("s,expected", [
    ("2026-09-12", datetime(2026, 9, 12, 23, 59, 59)),
    ("2026-09-12 16:10", datetime(2026, 9, 12, 16, 10, 59)),
    ("2026-09-12T16:10", datetime(2026, 9, 12, 16, 10, 59)),
    ("20260912", datetime(2026, 9, 12, 23, 59, 59)),
    ("20260912-16", datetime(2026, 9, 12, 16, 59, 59)),
    ("20260912-1610", datetime(2026, 9, 12, 16, 10, 59)),
    ("20260912-161023", datetime(2026, 9, 12, 16, 10, 23)),
])
def test_parse_time_arg_end_fills_missing_parts(s, expected):
    """until 补满：显式与紧凑两种写法必须一致（显式带分钟曾只补到 :00）。"""
    assert parse_time_arg(s, end=True) == expected


@pytest.mark.parametrize("bad", ["2026-13-01", "20260912-25", "20260912-1610238", "abc", "2026-9", "2026091"])
def test_parse_time_arg_rejects_invalid(bad):
    with pytest.raises(SystemExit):
        parse_time_arg(bad)


def test_sid_and_parent_for_subagent_two_uuid(env):
    recs = collect(env["sessions"], datetime(2026, 9, 10), datetime(2026, 9, 11, 23, 59, 59))
    sub = [r for r in recs if r.type == "subagent"]
    assert len(sub) == 1
    r = sub[0]
    # 子代理 ID 取文件名第二个 UUID，父线程来自 thread_spawn
    assert r.sid == env["ids"]["B"]
    assert r.parent == env["ids"]["A"]
    assert r.agent == "Feynman(sol_analyst)"


def test_paginated_pages_merge(env):
    recs = collect(env["sessions"], datetime(2026, 9, 11), datetime(2026, 9, 11, 23, 59, 59))
    pages = [r for r in recs if r.sid == env["ids"]["page"]]
    assert len(pages) == 1                      # 同线程分页合并为一个会话
    # 两页 token 相加：净输入 100+110=210（毛值含缓存 2000+2000）
    assert pages[0].models["gpt-5.6-luna"][0] == 4210
    assert pages[0].models["gpt-5.6-luna"][2] == 61


def test_two_uuid_user_file_keeps_thread_id(env):
    # 双 UUID 但非 subagent（翻页形态）；subagent 双 UUID 的覆盖见 test_sid_and_parent_for_subagent_two_uuid
    recs = collect(env["sessions"], datetime(2026, 9, 11), datetime(2026, 9, 11, 23, 59, 59))
    mystery = [r for r in recs if "gpt-mystery" in r.models]
    assert len(mystery) == 1


def test_window_filters_events_not_sessions(env):
    # 只取 09-11 09:00-10:00（本地）：gpt-mystery 会话的轮次在窗口内，分页第二页(14:00)在外
    since = datetime(2026, 9, 11, 9, 0)
    until = datetime(2026, 9, 11, 10, 0)
    recs = collect(env["sessions"], since, until)
    sids = {r.sid for r in recs}
    assert env["ids"]["C"] in sids              # 双 UUID user 文件取首 uuid（线程本体）
    assert env["ids"]["page"] in sids           # 分页首页 09:00 在窗口内（合并后会话计入）
    assert env["ids"]["A"] not in sids          # 09-10 的会话不在窗口


def test_empty_sessions_dropped(env):
    # 只有 meta 没有 token 事件的会话不出现（本夹具无此文件，验证解析器对空文件的行为）
    recs = collect(env["sessions"], datetime(2026, 9, 12), datetime(2026, 9, 12))
    assert recs == []


def test_zero_token_event_without_turn_context_dropped(tmp_path):
    """无 turn_context 且 token 全 0 的调用轮次不该带出 unknown 模型（calls 槽不参与过滤）。

    真实数据里这类事件会让 --by-model 多出一行「unknown 1 会话 全 0」。
    """
    import json

    sid = "01a00000-0000-4000-8000-00000000000a"
    path = tmp_path / f"rollout-2026-09-05T10-00-00-{sid}.jsonl"
    zero = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
            "reasoning_output_tokens": 0}
    path.write_text("\n".join([
        json.dumps({"timestamp": "2026-09-05T02:00:00.000Z", "type": "session_meta",
                    "payload": {"session_id": sid, "id": sid, "thread_source": "user",
                                "source": "vscode"}}),
        json.dumps({"timestamp": "2026-09-05T02:00:01.000Z", "type": "event_msg",
                    "payload": {"type": "token_count",
                                "info": {"last_token_usage": zero, "total_token_usage": zero}}}),
        json.dumps({"timestamp": "2026-09-05T02:00:02.000Z", "type": "turn_context",
                    "payload": {"model": "gpt-5.6-luna"}}),
        json.dumps({"timestamp": "2026-09-05T02:00:03.000Z", "type": "event_msg",
                    "payload": {"type": "token_count", "info": {
                        "last_token_usage": {"input_tokens": 1000, "cached_input_tokens": 400,
                                             "output_tokens": 50, "reasoning_output_tokens": 20},
                        "total_token_usage": {"input_tokens": 1000, "cached_input_tokens": 400,
                                              "output_tokens": 50}}}}),
    ]) + "\n")
    rec = parse_rollout(str(path))
    assert rec is not None
    assert set(rec.models) == {"gpt-5.6-luna"}     # unknown 空槽被丢弃
    assert rec.models["gpt-5.6-luna"][4] == 1      # 只计有 token 的那次调用


def test_archive_included_when_given(env):
    recs = collect(env["sessions"], datetime(2026, 9, 9), datetime(2026, 9, 11),
                   archive_dir=env["archive"])
    assert env["ids"]["arch"] in {r.sid for r in recs}
    recs2 = collect(env["sessions"], datetime(2026, 9, 9), datetime(2026, 9, 11, 23, 59, 59))
    assert env["ids"]["arch"] not in {r.sid for r in recs2}


# ---------------------------------------------------------------- 计量口径（累计差分）

UID = "01a09a5f-a44e-75e1-ba40-000000000001"
TS = "2026-09-11T01:00:00.000Z"


def _meta(uid=UID, thread_source="user"):
    return json.dumps({"timestamp": TS, "type": "session_meta",
                       "payload": {"session_id": uid, "id": uid, "cwd": "/tmp/p",
                                   "thread_source": thread_source, "source": "vscode"}})


def _turn(model):
    return json.dumps({"timestamp": TS, "type": "turn_context", "payload": {"model": model}})


def _settings(tier):
    return json.dumps({"timestamp": TS, "type": "event_msg",
                       "payload": {"type": "thread_settings_applied",
                                   "thread_settings": {"service_tier": tier}}})


def _usage(inp, cached, out, reasoning=0):
    return {"input_tokens": inp, "cached_input_tokens": cached,
            "output_tokens": out, "reasoning_output_tokens": reasoning}


def _tok(total=None, last=None):
    info = {}
    if total is not None:
        info["total_token_usage"] = total
    if last is not None:
        info["last_token_usage"] = last
    return json.dumps({"timestamp": TS, "type": "event_msg",
                       "payload": {"type": "token_count", "info": info}})


def _write(path, *lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def _rollout(tmp_path, *lines, name=f"rollout-2026-09-11T09-00-00-{UID}.jsonl"):
    return _write(tmp_path / "2026" / "09" / "11" / name, *lines)


def test_repeated_token_event_counted_once(tmp_path):
    """重复事件（累计值与 last 都相同）只计一次——旧口径会把 last 累加两次。"""
    path = _rollout(tmp_path, _meta(), _turn("gpt-x"),
                    _tok(_usage(100, 0, 10), _usage(100, 0, 10)),
                    _tok(_usage(100, 0, 10), _usage(100, 0, 10)))     # 完全重复
    rec = parse_rollout(path)
    assert rec is not None
    assert rec.models["gpt-x"][0] == 100 and rec.models["gpt-x"][2] == 10
    assert rec.models["gpt-x"][4] == 1                                # calls 只算一次
    assert rec.delta_sum == 220                                       # 旧口径对照保留


def test_inherited_first_snapshot_not_counted(tmp_path):
    """首帧整块是继承的父线程历史（last 全 0）时不能算进来。

    真实案例：某子代理文件首帧 total=14,051,760 而 last=0，旧口径记 235,038、
    不加判定会把整块 14M 记成它的用量。
    """
    path = _rollout(tmp_path, _meta(), _turn("gpt-x"),
                    _tok(_usage(14_000_000, 0, 51_760), _usage(0, 0, 0)),
                    _tok(_usage(14_010_000, 0, 52_000), _usage(10_000, 0, 240)))
    rec = parse_rollout(path)
    assert rec.models["gpt-x"][0] == 10_000
    assert rec.models["gpt-x"][2] == 240


def test_middle_jump_capped_by_last(tmp_path):
    """中间累计值跳升远超本轮 last（插入继承历史）时，以 last 封顶，不虚高。"""
    path = _rollout(tmp_path, _meta(), _turn("gpt-x"),
                    _tok(_usage(1_000, 0, 100), _usage(1_000, 0, 100)),
                    _tok(_usage(9_000_000, 0, 900_000), _usage(1_000, 0, 100)))
    rec = parse_rollout(path)
    assert rec.models["gpt-x"][0] == 2_000
    assert rec.models["gpt-x"][2] == 200


def test_cumulative_drop_falls_back_to_last(tmp_path):
    """上下文压缩让累计值回落时，该轮用 last_token_usage 并计数。"""
    path = _rollout(tmp_path, _meta(), _turn("gpt-x"),
                    _tok(_usage(100, 0, 10), _usage(100, 0, 10)),
                    _tok(_usage(60, 0, 6), _usage(60, 0, 6)))
    rec = parse_rollout(path)
    assert rec.resets == 1
    assert rec.models["gpt-x"][0] == 160 and rec.models["gpt-x"][2] == 16


def test_missing_total_falls_back_to_last(tmp_path):
    """缺 total_token_usage 时回退 last，不丢数据。"""
    path = _rollout(tmp_path, _meta(), _turn("gpt-x"),
                    _tok(None, _usage(500, 0, 50)),
                    _tok(None, _usage(300, 0, 30)))
    rec = parse_rollout(path)
    assert rec.fallbacks == 2
    assert rec.models["gpt-x"][0] == 800 and rec.models["gpt-x"][2] == 80


def test_tier_split_sums_back_to_model_totals(tmp_path):
    """thread_settings_applied 的档位单列，且各档合计等于模型总量（不变式）。"""
    path = _rollout(tmp_path, _meta(), _turn("gpt-x"),
                    _tok(_usage(100, 0, 10), _usage(100, 0, 10)),      # 未知档
                    _settings("priority"),
                    _tok(_usage(300, 0, 30), _usage(200, 0, 20)),      # Fast 档
                    _settings("default"),
                    _tok(_usage(600, 0, 60), _usage(300, 0, 30)))      # 标准档
    rec = parse_rollout(path)
    assert set(rec.tiers["gpt-x"]) == {"unknown", "priority", "default"}
    assert rec.tiers["gpt-x"]["priority"][0] == 200
    assert rec.tiers["gpt-x"]["default"][0] == 300
    for i in range(5):
        assert sum(t[i] for t in rec.tiers["gpt-x"].values()) == rec.models["gpt-x"][i]


def test_archived_duplicate_not_double_counted(tmp_path):
    """sessions/ 与 archived_sessions/ 同名（同 UUID）时以 sessions/ 为准，不累加两次。"""
    name = f"rollout-2026-09-11T09-00-00-{UID}.jsonl"
    body = (_meta(), _turn("gpt-x"), _tok(_usage(100, 0, 10), _usage(100, 0, 10)))
    active = _write(tmp_path / "sessions" / "2026" / "09" / "11" / name, *body)
    _write(tmp_path / "archived" / name, *body)
    recs = collect(str(tmp_path / "sessions"), datetime(2026, 9, 11), datetime(2026, 9, 11, 23, 59, 59),
                   archive_dir=str(tmp_path / "archived"))
    assert len(recs) == 1
    assert recs[0].models["gpt-x"][0] == 100          # 没有被累加成 200
    assert os.path.dirname(recs[0].file) == os.path.dirname(active)


def test_pagination_merge_keeps_tier_totals(tmp_path):
    """分页文件合并时 tiers 也要累加：曾漏合并，导致 tiers 合计比 models 少 4.81M 毛输入，
    分档计价随之少算（全库唯一破例来自分页会话）。"""
    uid2 = "01a09a5f-a44e-75e1-ba40-000000000002"
    _write(tmp_path / "2026" / "09" / "11" / f"rollout-2026-09-11T09-00-00-{UID}.jsonl",
           _meta(), _turn("gpt-x"), _settings("priority"),
           _tok(_usage(300, 0, 30), _usage(300, 0, 30)))
    _write(tmp_path / "2026" / "09" / "11" / f"rollout-2026-09-11T10-00-00-{UID}_{uid2}.jsonl",
           _meta(), _turn("gpt-x"), _settings("default"),
           _tok(_usage(200, 0, 20), _usage(200, 0, 20)))
    recs = collect(str(tmp_path), datetime(2026, 9, 11), datetime(2026, 9, 11, 23, 59, 59))
    assert len(recs) == 1
    rec = recs[0]
    assert rec.models["gpt-x"][0] == 500
    assert set(rec.tiers["gpt-x"]) == {"priority", "default"}
    for i in range(5):
        assert sum(t[i] for t in rec.tiers["gpt-x"].values()) == rec.models["gpt-x"][i]
