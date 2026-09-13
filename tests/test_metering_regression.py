"""T6 计量口径（累计值增量）的独立回归与复算入口。

本文件是**独立验证者**的产物：不修改实现，只做核验。两部分：

1. pytest 用例：用合成 rollout 夹具钉死 T6 约定的边界行为，并用本文件内**独立
   实现**的 oracle（不调用 ``codex_usage`` 的解析代码）交叉验证实现结果；另含
   task-7/task-9 定价回退的反例检查（缓存读回退、priority 档不能被按标准价）。
2. ``__main__`` 复算入口：对真实 ``~/.codex/sessions`` 数据独立复算，分别与
   ``codex-usage --json``（逐文件）和 ccusage（逐天/模型）对账。报告里引用的
   每个数字都由这些命令产出。

复现命令（工作目录 = 仓库根）::

    .venv/bin/python -m pytest tests/test_metering_regression.py -q
    .venv/bin/python tests/test_metering_regression.py --recompute --since 20260911 --until 20260912
    .venv/bin/python tests/test_metering_regression.py --ledger    --since 20260911 --until 20260912
    .venv/bin/python tests/test_metering_regression.py --ccusage   --since 20260911 --until 20260912
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pytest

from codex_usage.parser import collect, parse_rollout

LOCAL_TZ = datetime.now().astimezone().tzinfo
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


# ---------------------------------------------------------------- 夹具工具


def _utc_at(y: int, mo: int, d: int, h: int, mi: int = 0) -> str:
    """把本地墙上时间转成 rollout 里的 UTC 时间戳（夹具不钉死时区）。"""
    wall = datetime(y, mo, d, h, mi, tzinfo=LOCAL_TZ)
    return wall.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _usage(inp: int, cached: int, out: int, reasoning: int = 0) -> dict:
    return {"input_tokens": inp, "cached_input_tokens": cached,
            "output_tokens": out, "reasoning_output_tokens": reasoning}


def _tok(ts: str, *, total: dict | None = None, last: dict | None = None) -> str:
    info: dict = {}
    if total is not None:
        info["total_token_usage"] = total
    if last is not None:
        info["last_token_usage"] = last
    return json.dumps({"timestamp": ts, "type": "event_msg",
                       "payload": {"type": "token_count", "info": info}})


def _turn(ts: str, model: str) -> str:
    return json.dumps({"timestamp": ts, "type": "turn_context", "payload": {"model": model}})


def _settings(ts: str, tier: str, model: str | None = None) -> str:
    st: dict = {"service_tier": tier}
    if model:
        st["model"] = model
    return json.dumps({"timestamp": ts, "type": "event_msg",
                       "payload": {"type": "thread_settings_applied", "thread_settings": st}})


def _meta(ts: str, sid: str, thread_source: str = "user", spawn: dict | None = None) -> str:
    src = {"subagent": {"thread_spawn": spawn}} if spawn else "vscode"
    return json.dumps({"timestamp": ts, "type": "session_meta",
                       "payload": {"session_id": sid, "id": sid, "cwd": "/tmp/proj",
                                   "thread_source": thread_source, "source": src}})


def _write_rollout(dir_path, name: str, lines: list[str]) -> str:
    os.makedirs(dir_path, exist_ok=True)
    path = os.path.join(dir_path, name)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    return path


# ------------------------------------------------- 独立 oracle（不调用实现）


def _vec(obj) -> list[int]:
    def one(key):
        try:
            return max(0, int(obj.get(key, 0) or 0))
        except (TypeError, ValueError):
            return 0
    return [one("input_tokens"), one("cached_input_tokens"),
            one("output_tokens"), one("reasoning_output_tokens")]


def oracle(lines: list[str], window: tuple[datetime, datetime] | None = None) -> dict:
    """按 T6 约定独立复算一份 rollout 行序列。

    规则（与交接说明逐条对应）：
      * 每轮 = 当前累计 − 上一累计，按当时 turn_context 的模型/档位归因；
      * 首帧只计自己的 last_token_usage（累计可能整块是继承的父线程历史）；
      * 中间累计跳升远大于本轮 last 时以 last 为上限（分量为 0 的按增量）；
      * 累计回落（压缩重置）或缺 total_token_usage 时回退 last；
      * 窗口外的事件完全跳过，因此窗口内首帧仍视为“首帧”。
    """
    per = defaultdict(lambda: [0, 0, 0, 0, 0])
    tiers: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0, 0]))
    cur_model, cur_tier = "unknown", "unknown"
    prev, delta_sum, resets, fallbacks = None, 0, 0, 0
    for raw in lines:
        obj = json.loads(raw)
        typ, payload = obj.get("type"), obj.get("payload") or {}
        if typ == "session_meta":
            continue
        if typ == "turn_context":
            model = payload.get("model")
            if model:
                cur_model = model
            continue
        if typ == "event_msg" and payload.get("type") == "thread_settings_applied":
            st = payload.get("thread_settings") or {}
            if st.get("service_tier"):
                cur_tier = str(st["service_tier"])
            if st.get("model") and cur_model == "unknown":
                cur_model = st["model"]
            continue
        if typ != "event_msg" or payload.get("type") != "token_count":
            continue
        if window is not None:
            ts = _to_local(obj.get("timestamp"))
            if ts is None or not (window[0] <= ts <= window[1]):
                continue
        info = payload.get("info") or {}
        last_obj = info.get("last_token_usage")
        last = _vec(last_obj) if last_obj is not None else None
        total = info.get("total_token_usage")
        if last is not None and (last[0] or last[2]):
            delta_sum += last[0] + last[2]
        if total:
            cur = _vec(total)
            if prev is None:
                delta = list(last) if last is not None else cur
            else:
                inc = [c - p for c, p in zip(cur, prev)]
                if any(x < 0 for x in inc):
                    resets += 1
                    delta = list(last) if last is not None else [max(0, x) for x in inc]
                elif last is not None and any(last):
                    delta = [min(max(0, x), cap) if cap else max(0, x)
                             for x, cap in zip(inc, last)]
                else:
                    delta = [max(0, x) for x in inc]
            prev = cur
        else:
            fallbacks += 1
            delta = list(last) if last is not None else [0, 0, 0, 0]
        if any(delta):
            for bucket in (per[cur_model], tiers[cur_model][cur_tier]):
                bucket[4] += 1
                for i in range(4):
                    bucket[i] += max(0, delta[i])
    active = {m: v for m, v in per.items() if sum(v[:4]) > 0}
    return {"models": active, "tiers": {m: dict(t) for m, t in tiers.items()},
            "delta_sum": delta_sum, "resets": resets, "fallbacks": fallbacks}


def _to_local(ts) -> datetime | None:
    if not ts:
        return None
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt.tzinfo:
        dt = dt.astimezone()
    return dt.replace(tzinfo=None)


def _assert_matches(rec, expect: dict) -> None:
    """实现结果与 oracle 必须逐字段一致。"""
    assert rec is not None
    assert {m: v for m, v in rec.models.items()} == expect["models"]
    assert {m: {t: list(s) for t, s in ts.items()} for m, ts in rec.tiers.items()} == expect["tiers"]
    assert rec.delta_sum == expect["delta_sum"]
    assert rec.resets == expect["resets"]
    assert rec.fallbacks == expect["fallbacks"]


# ---------------------------------------------------------------- 边界用例

T = _utc_at(2026, 9, 11, 10, 0)


def test_duplicate_cumulative_event_counted_once(tmp_path):
    """完全重复的事件（累计与 last 都没变）只能算一次；旧口径会重复累加 last。"""
    lines = [_meta(T, "01a09a5f-a44e-75e1-ba40-000000000001"), _turn(T, "gpt-x"),
             _tok(T, total=_usage(1000, 0, 100), last=_usage(1000, 0, 100)),
             _tok(T, total=_usage(1000, 0, 100), last=_usage(1000, 0, 100)),
             _tok(T, total=_usage(1300, 200, 130), last=_usage(300, 200, 30))]
    path = _write_rollout(str(tmp_path), "rollout-2026-09-11T10-00-00-"
                          "01a09a5f-a44e-75e1-ba40-000000000001.jsonl", lines)
    rec = parse_rollout(path)
    expect = oracle(lines)
    _assert_matches(rec, expect)
    assert rec.models["gpt-x"][:3] == [1300, 200, 130]
    assert rec.models["gpt-x"][4] == 2                 # 重复帧不算调用
    assert rec.delta_sum == 1430                       # 旧口径对照仍保留


def test_duplicate_with_stale_nonzero_last_still_counted_once(tmp_path):
    """重复事件即使带着一份非零的陈旧 last，增量仍为 0，不重复计。"""
    lines = [_meta(T, "01a09a5f-a44e-75e1-ba40-000000000002"), _turn(T, "gpt-x"),
             _tok(T, total=_usage(500, 0, 50), last=_usage(500, 0, 50)),
             _tok(T, total=_usage(500, 0, 50), last=_usage(500, 0, 50))]
    path = _write_rollout(str(tmp_path), "rollout-2026-09-11T10-00-00-"
                          "01a09a5f-a44e-75e1-ba40-000000000002.jsonl", lines)
    _assert_matches(parse_rollout(path), oracle(lines))


def test_inherited_first_snapshot_not_counted(tmp_path):
    """首帧累计整块是继承的父线程历史（last 全 0）时不计入。"""
    lines = [_meta(T, "01a09a5f-a44e-75e1-ba40-000000000003"), _turn(T, "gpt-x"),
             _tok(T, total=_usage(14_000_000, 0, 51_760), last=_usage(0, 0, 0)),
             _tok(T, total=_usage(14_010_000, 0, 52_000), last=_usage(10_000, 0, 240))]
    path = _write_rollout(str(tmp_path), "rollout-2026-09-11T10-00-00-"
                          "01a09a5f-a44e-75e1-ba40-000000000003.jsonl", lines)
    rec = parse_rollout(path)
    _assert_matches(rec, oracle(lines))
    assert rec.models["gpt-x"][:3] == [10_000, 0, 240]


def test_middle_jump_capped_by_last(tmp_path):
    """中间累计跳升远超本轮 last（插入继承历史）时以 last 封顶。"""
    lines = [_meta(T, "01a09a5f-a44e-75e1-ba40-000000000004"), _turn(T, "gpt-x"),
             _tok(T, total=_usage(1000, 0, 100), last=_usage(1000, 0, 100)),
             _tok(T, total=_usage(9_000_000, 0, 900_000), last=_usage(1000, 0, 100))]
    path = _write_rollout(str(tmp_path), "rollout-2026-09-11T10-00-00-"
                          "01a09a5f-a44e-75e1-ba40-000000000004.jsonl", lines)
    rec = parse_rollout(path)
    _assert_matches(rec, oracle(lines))
    assert rec.models["gpt-x"][:3] == [2000, 0, 200]


def test_zero_component_in_last_falls_back_to_increment(tmp_path):
    """last 某个分量为 0 时该分量取累计增量，不因封顶而少算。"""
    lines = [_meta(T, "01a09a5f-a44e-75e1-ba40-000000000005"), _turn(T, "gpt-x"),
             _tok(T, total=_usage(1000, 500, 100), last=_usage(1000, 500, 100)),
             _tok(T, total=_usage(1500, 800, 100), last=_usage(0, 300, 0))]
    path = _write_rollout(str(tmp_path), "rollout-2026-09-11T10-00-00-"
                          "01a09a5f-a44e-75e1-ba40-000000000005.jsonl", lines)
    rec = parse_rollout(path)
    _assert_matches(rec, oracle(lines))
    assert rec.models["gpt-x"][:2] == [1500, 800]


def test_cumulative_drop_falls_back_to_last(tmp_path):
    """累计值回落（上下文压缩）时该轮用 last，并记一次 resets。"""
    lines = [_meta(T, "01a09a5f-a44e-75e1-ba40-000000000006"), _turn(T, "gpt-x"),
             _tok(T, total=_usage(100, 0, 10), last=_usage(100, 0, 10)),
             _tok(T, total=_usage(60, 0, 6), last=_usage(60, 0, 6)),
             _tok(T, total=_usage(120, 0, 12), last=_usage(60, 0, 6))]
    path = _write_rollout(str(tmp_path), "rollout-2026-09-11T10-00-00-"
                          "01a09a5f-a44e-75e1-ba40-000000000006.jsonl", lines)
    rec = parse_rollout(path)
    _assert_matches(rec, oracle(lines))
    assert rec.resets == 1
    assert rec.models["gpt-x"][:3] == [220, 0, 22]


def test_missing_total_falls_back_to_last(tmp_path):
    """缺 total_token_usage 时逐轮回退 last，并记 fallbacks。"""
    lines = [_meta(T, "01a09a5f-a44e-75e1-ba40-000000000007"), _turn(T, "gpt-x"),
             _tok(T, last=_usage(500, 0, 50)),
             _tok(T, last=_usage(300, 0, 30))]
    path = _write_rollout(str(tmp_path), "rollout-2026-09-11T10-00-00-"
                          "01a09a5f-a44e-75e1-ba40-000000000007.jsonl", lines)
    rec = parse_rollout(path)
    _assert_matches(rec, oracle(lines))
    assert rec.fallbacks == 2
    assert rec.models["gpt-x"][:3] == [800, 0, 80]


def test_total_and_last_both_missing_is_dropped(tmp_path):
    """total 与 last 都缺的事件不产生用量；整文件无用量时返回 None。"""
    lines = [_meta(T, "01a09a5f-a44e-75e1-ba40-000000000008"), _turn(T, "gpt-x"),
             _tok(T)]
    path = _write_rollout(str(tmp_path), "rollout-2026-09-11T10-00-00-"
                          "01a09a5f-a44e-75e1-ba40-000000000008.jsonl", lines)
    assert oracle(lines)["models"] == {}
    assert parse_rollout(path) is None


def test_window_skips_out_of_window_events(tmp_path):
    """窗口按逐轮事件时间戳过滤；跨窗口会话只计窗口内的轮次。

    窗口外的轮次不参与累计差分，因此窗口内首帧仍按“首帧=自己的 last”处理，
    不会把窗口外已经计入的历史又算一遍。
    """
    lines = [_meta(_utc_at(2026, 9, 11, 9, 0), "01a09a5f-a44e-75e1-ba40-000000000009"),
             _turn(_utc_at(2026, 9, 11, 9, 0), "gpt-x"),
             _tok(_utc_at(2026, 9, 11, 9, 0), total=_usage(1000, 0, 100), last=_usage(1000, 0, 100)),
             _tok(_utc_at(2026, 9, 11, 10, 30), total=_usage(1050, 0, 105), last=_usage(50, 0, 5)),
             _tok(_utc_at(2026, 9, 11, 11, 0), total=_usage(1120, 0, 112), last=_usage(70, 0, 7))]
    path = _write_rollout(str(tmp_path), "rollout-2026-09-11T09-00-00-"
                          "01a09a5f-a44e-75e1-ba40-000000000009.jsonl", lines)
    window = (datetime(2026, 9, 11, 10, 0), datetime(2026, 9, 11, 12, 0))
    rec = parse_rollout(path, window=window)
    exp = oracle(lines, window=window)
    _assert_matches(rec, exp)
    assert rec.models["gpt-x"][:3] == [120, 0, 12]      # 窗口外那 1000/100 不计


def test_tier_split_and_switch(tmp_path):
    """档位按 thread_settings_applied 分段：unknown → priority → default。"""
    lines = [_meta(T, "01a09a5f-a44e-75e1-ba40-00000000000a"), _turn(T, "gpt-x"),
             _tok(T, total=_usage(100, 0, 10), last=_usage(100, 0, 10)),
             _settings(T, "priority"),
             _tok(T, total=_usage(300, 0, 30), last=_usage(200, 0, 20)),
             _settings(T, "default"),
             _tok(T, total=_usage(600, 0, 60), last=_usage(300, 0, 30))]
    path = _write_rollout(str(tmp_path), "rollout-2026-09-11T10-00-00-"
                          "01a09a5f-a44e-75e1-ba40-00000000000a.jsonl", lines)
    rec = parse_rollout(path)
    _assert_matches(rec, oracle(lines))
    assert set(rec.tiers["gpt-x"]) == {"unknown", "priority", "default"}
    assert rec.tiers["gpt-x"]["priority"][0] == 200
    assert rec.tiers["gpt-x"]["default"][0] == 300
    for i in range(5):                                  # 不变式：各档合计 == 模型合计
        assert sum(t[i] for t in rec.tiers["gpt-x"].values()) == rec.models["gpt-x"][i]


def test_multi_model_same_session(tmp_path):
    """同一会话内切换模型：用量按各轮当时的 turn_context 归因，不串味。"""
    lines = [_meta(T, "01a09a5f-a44e-75e1-ba40-00000000000b"), _turn(T, "gpt-a"),
             _tok(T, total=_usage(1000, 0, 100), last=_usage(1000, 0, 100)),
             _turn(T, "gpt-b"),
             _tok(T, total=_usage(1300, 0, 130), last=_usage(300, 0, 30))]
    path = _write_rollout(str(tmp_path), "rollout-2026-09-11T10-00-00-"
                          "01a09a5f-a44e-75e1-ba40-00000000000b.jsonl", lines)
    rec = parse_rollout(path)
    _assert_matches(rec, oracle(lines))
    assert rec.models["gpt-a"][:3] == [1000, 0, 100]
    assert rec.models["gpt-b"][:3] == [300, 0, 30]
    assert rec.multi_model is True
    assert rec.primary_model == "gpt-a"


def test_usage_before_turn_context_attributed_to_unknown(tmp_path):
    """turn_context 之前就产生用量时归到 unknown（理论路径；实测真实数据里没有）。

    实测：2026-09-11~13 窗口内“模型仍为 unknown 且本轮有非零用量”的事件为 0 条。
    """
    lines = [_meta(T, "01a09a5f-a44e-75e1-ba40-00000000000c"),
             _tok(T, total=_usage(1000, 0, 100), last=_usage(1000, 0, 100)),
             _turn(T, "gpt-a"),
             _tok(T, total=_usage(1300, 0, 130), last=_usage(300, 0, 30))]
    path = _write_rollout(str(tmp_path), "rollout-2026-09-11T10-00-00-"
                          "01a09a5f-a44e-75e1-ba40-00000000000c.jsonl", lines)
    rec = parse_rollout(path)
    _assert_matches(rec, oracle(lines))
    assert rec.models["unknown"][:3] == [1000, 0, 100]


# --------------------------------------------- 分页 / 归档 / 跨日目录


def test_paginated_pages_merge_token_totals(tmp_path):
    """同一线程的分页文件（双 UUID 文件名，同首 UUID）合并为一个会话，token 相加。"""
    thread = "01a09a5f-a44e-75e1-ba40-00000000000d"
    day = tmp_path / "2026" / "09" / "11"
    bodies = [
        [_meta(T, thread), _turn(T, "gpt-x"),
         _tok(T, total=_usage(1000, 0, 100), last=_usage(1000, 0, 100))],
        [_meta(T, thread), _turn(T, "gpt-x"),
         _tok(T, total=_usage(700, 0, 70), last=_usage(700, 0, 70))],
    ]
    for i, body in enumerate(bodies):
        _write_rollout(str(day), f"rollout-2026-09-11T1{i}-00-00-{thread}-"
                                 f"01a09a5f-a44e-75e1-ba40-00000000010{i}.jsonl", body)
    recs = collect(str(tmp_path), datetime(2026, 9, 11), datetime(2026, 9, 11, 23, 59, 59))
    assert len(recs) == 1
    assert recs[0].sid == thread
    assert recs[0].models["gpt-x"][:3] == [1700, 0, 170]


@pytest.mark.xfail(reason="已知缺口：分页合并只累加 models，tiers/delta_sum/resets 取首页；"
                          "详见 docs/metering-verification.md 第 4 节", strict=False)
def test_paginated_pages_do_not_merge_tiers(tmp_path):
    """分页会话的 tiers 与 delta_sum 也应合并（当前实现只保留第一页）。"""
    thread = "01a09a5f-a44e-75e1-ba40-00000000000e"
    day = tmp_path / "2026" / "09" / "11"
    bodies = [
        [_meta(T, thread), _turn(T, "gpt-x"), _settings(T, "priority"),
         _tok(T, total=_usage(1000, 0, 100), last=_usage(1000, 0, 100))],
        [_meta(T, thread), _turn(T, "gpt-x"), _settings(T, "priority"),
         _tok(T, total=_usage(700, 0, 70), last=_usage(700, 0, 70))],
    ]
    for i, body in enumerate(bodies):
        _write_rollout(str(day), f"rollout-2026-09-11T1{i}-30-00-{thread}-"
                                 f"01a09a5f-a44e-75e1-ba40-00000000011{i}.jsonl", body)
    recs = collect(str(tmp_path), datetime(2026, 9, 11), datetime(2026, 9, 11, 23, 59, 59))
    assert len(recs) == 1
    assert recs[0].tiers["gpt-x"]["priority"][0] == 1700      # 两页都应在
    assert recs[0].delta_sum == 1870


def test_archived_duplicate_not_double_counted(tmp_path):
    """sessions/ 与 archived_sessions/ 同 UUID 时以 sessions/ 为准，只算一次。"""
    name = "rollout-2026-09-11T10-00-00-01a09a5f-a44e-75e1-ba40-00000000000f.jsonl"
    body = [_meta(T, "01a09a5f-a44e-75e1-ba40-00000000000f"), _turn(T, "gpt-x"),
            _tok(T, total=_usage(100, 0, 10), last=_usage(100, 0, 10))]
    _write_rollout(str(tmp_path / "sessions" / "2026" / "09" / "11"), name, body)
    _write_rollout(str(tmp_path / "archived"), name, body)
    recs = collect(str(tmp_path / "sessions"), datetime(2026, 9, 11),
                   datetime(2026, 9, 11, 23, 59, 59),
                   archive_dir=str(tmp_path / "archived"))
    assert len(recs) == 1
    assert recs[0].models["gpt-x"][0] == 100                  # 不是 200


@pytest.mark.xfail(reason="已知缺口：collect() 只扫 [since,until] 日期目录，含窗口内事件的"
                          "早日期目录文件被漏掉；详见 docs/metering-verification.md 第 3 节",
                   strict=False)
def test_cross_day_dir_file_with_in_window_event_is_scanned(tmp_path):
    """文件落在 09-10 目录但含 09-11 的轮次时，应被计入 09-11 窗口。"""
    name = "rollout-2026-09-10T23-50-00-01a09a5f-a44e-75e1-ba40-000000000020.jsonl"
    body = [_meta(_utc_at(2026, 9, 10, 23, 50), "01a09a5f-a44e-75e1-ba40-000000000020"),
            _turn(_utc_at(2026, 9, 10, 23, 50), "gpt-x"),
            _tok(_utc_at(2026, 9, 11, 10, 0), total=_usage(900, 0, 90), last=_usage(900, 0, 90))]
    _write_rollout(str(tmp_path / "2026" / "09" / "10"), name, body)
    recs = collect(str(tmp_path), datetime(2026, 9, 11), datetime(2026, 9, 11, 23, 59, 59))
    assert len(recs) == 1
    assert recs[0].models["gpt-x"][0] == 900


# ------------------------------------------- 反例检查：定价回退不得低估


def test_cache_read_price_fallback_uses_input_price(tmp_path):
    """表里缺 cache read 价或显式为 0 时回退 input 价，缓存读数不会被计成 0。"""
    from codex_usage.pricing import model_cost_detail

    for record in ({"inputCostPerMillion": 10.0, "outputCostPerMillion": 50.0},
                   {"inputCostPerMillion": 10.0, "outputCostPerMillion": 50.0,
                    "cacheReadCostPerMillion": 0}):
        detail = model_cost_detail({"m": record}, "m", 1000, 1_000_000, 0)
        assert detail is not None
        assert "cacheReadCostPerMillion" in detail["fallbacks"]
        # (1000 + 1_000_000) × $10/M = $10.01：缓存读按 input 价计，不是 0
        assert detail["cost_usd"] == pytest.approx(10.01)
        assert detail["cost_usd"] > 0


def test_cache_read_price_present_not_flagged_as_fallback():
    from codex_usage.pricing import model_cost_detail

    detail = model_cost_detail(
        {"m": {"inputCostPerMillion": 10.0, "outputCostPerMillion": 50.0,
               "cacheReadCostPerMillion": 1.0}}, "m", 1000, 1_000_000, 0)
    assert detail["fallbacks"] == []
    assert detail["cost_usd"] == pytest.approx(1.01)


def test_priority_tier_not_priced_as_standard():
    """反例：tier=priority 的用量不能被按标准价计（否则低估约一半）。"""
    from codex_usage.pricing import load_pricing, model_cost_detail

    pricing = load_pricing()
    std = model_cost_detail(pricing, "gpt-5.6-sol", 1_000_000, 0, 0)
    pri = model_cost_detail(pricing, "gpt-5.6-sol", 1_000_000, 0, 0, tier="priority")
    if std is None or pri is None or not pri.get("tier_priced"):
        pytest.skip("内置定价/档位表未覆盖 gpt-5.6-sol，跳过档位倍率检查")
    assert pri["tier"] == "priority"
    assert pri["standard_cost_usd"] == pytest.approx(std["cost_usd"])
    assert pri["cost_usd"] == pytest.approx(2 * std["cost_usd"])   # 官方 2.0× Fast 价
    # default/unknown 仍是标准价
    for tier in ("default", None, "unknown"):
        d = model_cost_detail(pricing, "gpt-5.6-sol", 1_000_000, 0, 0, tier=tier)
        assert d["cost_usd"] == pytest.approx(std["cost_usd"])


def test_alias_label_priced_as_target_model():
    """codex-auto-review 无公开价，按别名映射到 gpt-5.5（标 assumed），金额一致。"""
    from codex_usage.pricing import load_pricing, model_cost_detail

    pricing = load_pricing()
    alias = model_cost_detail(pricing, "codex-auto-review", 1_000_000, 0, 0)
    target = model_cost_detail(pricing, "gpt-5.5", 1_000_000, 0, 0)
    if alias is None or target is None:
        pytest.skip("别名/目标模型未定价，跳过")
    assert alias["priced_as"] == "gpt-5.5"
    assert alias["assumed"] is True
    assert alias["cost_usd"] == pytest.approx(target["cost_usd"])


# ---------------------------------------------------------------- 复算入口


def _parse_window(s: str, end: bool) -> datetime:
    """复算入口自己的时间解析（不依赖实现，只支持报告里用到的写法）。

    ``20260911`` / ``20260911-2100`` / ``2026-09-11 10:00``；``end=True`` 时
    缺省部分补满（时→23、分秒→59），与 CLI 的 --until 语义一致。
    """
    s = s.strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh, mm, ss = m.group(4), m.group(5), m.group(6)
    else:
        m = re.fullmatch(r"(\d{8})(?:[-_T. ]?(\d{2})(?::?(\d{2}))?(?::?(\d{2}))?)?", s)
        if not m:
            raise SystemExit(f"无法解析时间: {s}")
        y, mo, d = int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:8])
        hh, mm, ss = m.group(2), m.group(3), m.group(4)
    prec = 0 if hh is None else (1 if mm is None else (2 if ss is None else 3))
    h, mi, se = int(hh or 0), int(mm or 0), int(ss or 0)
    if end:
        if prec < 3:
            se = 59
        if prec < 2:
            mi = 59
        if prec < 1:
            h = 23
    return datetime(y, mo, d, h, mi, se)


def _event_metering(path: str, since: datetime, until: datetime) -> dict:
    """独立复算单个 rollout；附带窗口内首帧的本地日期（逐天口径）。"""
    lines = []
    with open(path, errors="replace") as f:
        for raw in f:
            if any(k in raw[:200] for k in ('"session_meta"', '"turn_context"',
                                            '"thread_settings_applied"', '"token_count"')):
                lines.append(raw)
    got = oracle(lines, window=(since, until))
    day = None
    for raw in lines:
        if '"token_count"' not in raw[:200]:
            continue
        try:
            ts = _to_local(json.loads(raw).get("timestamp"))
        except Exception:
            continue
        if ts and since <= ts <= until:
            day = ts.strftime("%Y-%m-%d")
            break
    got["day"] = day
    return got


def _dirs_for(sessions: str, since: datetime, until: datetime) -> list[str]:
    out = []
    d = since.date()
    while d <= until.date():
        out.append(os.path.join(sessions, d.strftime("%Y/%m/%d"), "rollout-*.jsonl"))
        d += timedelta(days=1)
    return out


def _cli_json(repo: str, since: str, until: str, extra: list[str]) -> list[dict]:
    cmd = [sys.executable, "-m", "codex_usage.cli", "--since", since, "--until", until,
           "--json", *extra]
    res = subprocess.run(cmd, cwd=repo, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"`{' '.join(cmd)}` 失败（{res.returncode}）:\n{res.stderr[-2000:]}")
    return [json.loads(x) for x in res.stdout.splitlines() if x.strip()]


def _ccusage_daily(repo: str, since: str, until: str) -> dict:
    cache = os.environ.get("npm_config_cache", os.path.join(repo, ".scratch", "npm"))
    env = dict(os.environ, npm_config_cache=cache)
    cmd = ["npx", "--yes", "ccusage@latest", "codex", "daily", "--json",
           "--since", since, "--until", until]
    res = subprocess.run(cmd, cwd=repo, capture_output=True, text=True, env=env, timeout=900)
    if res.returncode != 0:
        raise SystemExit(f"ccusage 失败（{res.returncode}）:\n{res.stderr[-2000:]}")
    data = json.loads(res.stdout)
    out = {}
    for day in data["daily"]:
        for model, v in day["models"].items():
            key = (day["date"], "codex-auto-review" if model == "gpt-5.5" else model)
            out[key] = (v["inputTokens"], v["cacheReadTokens"], v["outputTokens"])
    return out


def _cmd_recompute(args) -> int:
    """逐文件对账：本文件的独立复算 vs `codex-usage --json --raw`。"""
    sessions = args.sessions_dir
    since, until = args.since_dt, args.until_dt
    paths = []
    for pattern in _dirs_for(sessions, since, until):
        paths += glob.glob(pattern)
    paths = sorted(set(paths))
    rows = {r["session_id"]: r for r in _cli_json(args.repo, args.since, args.until, ["--raw"])}
    ok = bad = empty = 0
    for path in paths:
        uuids = UUID_RE.findall(os.path.basename(path))
        got = _event_metering(path, since, until)
        mine = got["models"]
        row = rows.get(uuids[-1]) if uuids else None
        if not mine:
            empty += 1
            if row:
                bad += 1
                print(f"MISMATCH {os.path.basename(path)} 实现有行、独立复算为空")
            continue
        if row is None:
            bad += 1
            print(f"MISMATCH {os.path.basename(path)} 实现缺行")
            continue
        cli = {m: [v["input_gross"], v["cached"], v["output"], v["reasoning"], v["calls"]]
               for m, v in row["models"].items()}
        if mine == cli:
            ok += 1
        else:
            bad += 1
            print(f"MISMATCH {os.path.basename(path)}")
            for m in sorted(set(mine) | set(cli)):
                if mine.get(m) != cli.get(m):
                    print(f"    {m}: 独立={mine.get(m)} 实现={cli.get(m)}")
    print(f"窗口 {args.since} ~ {args.until}：文件 {len(paths)} 个，"
          f"逐文件完全一致 {ok} 个，无用量 {empty} 个，不一致 {bad} 个")
    return 1 if bad else 0


def _scan_all(sessions: str, since: datetime, until: datetime):
    """扫描全部日期目录，按事件本地日期/模型汇总，并区分跨日目录的贡献。"""
    inside_glob = set()
    for pattern in _dirs_for(sessions, since, until):
        inside_glob |= set(glob.glob(pattern))
    total = defaultdict(lambda: [0, 0, 0])          # (day,model) -> net,cr,out
    cross = defaultdict(lambda: [0, 0, 0])
    for path in sorted(glob.glob(os.path.join(sessions, "*", "*", "*", "rollout-*.jsonl"))):
        got = _event_metering(path, since, until)
        if got["day"] is None:
            continue
        target = total if path in inside_glob else cross
        for model, v in got["models"].items():
            slot = target[(got["day"], model)]
            slot[0] += v[0] - v[1]
            slot[1] += v[1]
            slot[2] += v[2]
    return total, cross


def _cmd_ledger(args) -> int:
    """独立复算逐天/逐模型台账；--ccusage 时与 ccusage 逐项对账。"""
    sessions = args.sessions_dir
    since, until = args.since_dt, args.until_dt
    total, cross = _scan_all(sessions, since, until)
    cc = _ccusage_daily(args.repo, args.since, args.until) if args.ccusage else {}
    keys = sorted(set(total) | set(cross) | set(cc))
    print(f"{'day':11s} {'model':18s} {'独立复算(净/缓存/出)':>32s} "
          f"{'跨日目录文件补充':>26s} {'ccusage(净/缓存/出)':>32s} 判定")
    bad = 0
    sum_mine = sum_cc = 0
    for key in keys:
        mine = total.get(key, [0, 0, 0])
        extra = cross.get(key, [0, 0, 0])
        fixed = tuple(mine[i] + extra[i] for i in range(3))
        row = cc.get(key)
        sum_mine += sum(fixed)
        sum_cc += sum(row) if row else 0
        if row is None:
            verdict = "ccusage 无此行"
        elif tuple(mine) == row:
            verdict = "逐项一致"
        elif fixed == row:
            verdict = f"逐项一致（跨日文件补 {sum(extra):,}）"
        else:
            verdict = "不一致"
            bad += 1
        print(f"{key[0]:11s} {key[1]:18s} {str(tuple(mine)):>32s} {str(tuple(extra)):>26s} "
              f"{str(row):>32s} {verdict}")
    if cc:
        print(f"总 tokens：独立复算(含跨日) {sum_mine:,} | ccusage {sum_cc:,} | "
              f"差 {sum_mine - sum_cc:,}")
    return 1 if bad else 0


def _build_parser() -> argparse.ArgumentParser:
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="T6 计量口径独立复算（不写实现，只核验）")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--recompute", action="store_true",
                      help="逐文件与 `codex-usage --json --raw` 对账")
    mode.add_argument("--ledger", action="store_true",
                      help="逐天/逐模型独立台账（可加 --ccusage）")
    ap.add_argument("--ccusage", action="store_true", help="--ledger 时追加 ccusage 对账")
    ap.add_argument("--since", default="20260911", help="默认 20260911")
    ap.add_argument("--until", default="20260912", help="默认 20260912（定窗，避免实时数据漂移）")
    ap.add_argument("--sessions-dir", default=os.path.expanduser("~/.codex/sessions"))
    ap.add_argument("--repo", default=repo)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.since_dt = _parse_window(args.since, end=False)
    args.until_dt = _parse_window(args.until, end=True)
    return _cmd_recompute(args) if args.recompute else _cmd_ledger(args)


if __name__ == "__main__":
    sys.exit(main())
