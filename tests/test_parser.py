"""解析器单元测试：会话 ID 规则、父子归属、分页合并、时间窗口、时间参数格式。"""

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
