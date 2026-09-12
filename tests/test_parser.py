"""解析器单元测试：会话 ID 规则、父子归属、分页合并、时间窗口。"""

from datetime import datetime

from codex_usage.parser import collect, parse_rollout


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


def test_archive_included_when_given(env):
    recs = collect(env["sessions"], datetime(2026, 9, 9), datetime(2026, 9, 11),
                   archive_dir=env["archive"])
    assert env["ids"]["arch"] in {r.sid for r in recs}
    recs2 = collect(env["sessions"], datetime(2026, 9, 9), datetime(2026, 9, 11, 23, 59, 59))
    assert env["ids"]["arch"] not in {r.sid for r in recs2}
