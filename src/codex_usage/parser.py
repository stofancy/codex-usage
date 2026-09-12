"""rollout 会话文件解析：从 ~/.codex/sessions 的 JSONL 提取会话与逐模型 token 用量。

解析口径（实测钉死的事实，改这里前先看 tests/fixtures 的样例）：
- 会话 ID 取文件名 UUID；`rollout-<ts>-<A>_<B>.jsonl` 且 thread_source=subagent 时，
  A 是父线程、B 是子代理本尊；非 subagent 的同线程多文件（分页）按 ID 合并。
- 子代理文件的 session_meta.session_id 存的是父线程 ID，不可作会话 ID。
- input_tokens 是含缓存的毛值，净输入 = input - cached_input。
- token 计量用每轮 token_count.last_token_usage（单轮增量）按当时 turn_context 的模型归因；
  total_token_usage 会在上下文压缩时重置，不作总量依据，仅在记录中留作参考。
- 时间过滤按逐轮事件时间戳（UTC→本地时间）判定，跨窗口会话只统计窗口内的轮次。
"""

import glob
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict

UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TYPE_SHORT = {"user": "user", "subagent": "subagent", "guardian_review": "guardian",
              "voice_chat": "voice", "chatgpt_handoff": "handoff",
              "agent_created_thread": "agent"}


@dataclass
class Session:
    file: str
    sid: str
    uuids: list[str]
    type: str | None = None
    parent: str | None = None
    agent: str | None = None
    start: str | None = None
    cwd: str | None = None
    # model -> [gross_in, cached, out, reasoning]
    models: dict[str, list[int]] = field(default_factory=dict)
    first_local: datetime | None = None
    last_local: datetime | None = None
    final_total: list[int] | None = None
    primary_model: str = "unknown"
    multi_model: bool = False


def to_local(ts) -> datetime | None:
    """ISO 时间戳（UTC）→ 本地 naive datetime。"""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone()
        return dt.replace(tzinfo=None)
    except Exception:
        return None


def parse_time_arg(s: str, end: bool = False) -> datetime:
    """'YYYY-MM-DD[ HH:MM[:SS]]' → datetime；纯日期默认 00:00 /（end=True 时）23:59:59。"""
    s = s.strip()
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
              "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%Y%m%d"):
        try:
            dt = datetime.strptime(s, f)
            if "%H" not in f and end:
                dt = dt.replace(hour=23, minute=59, second=59)
            return dt
        except ValueError:
            continue
    raise SystemExit(f"无法解析时间: {s}（支持 YYYY-MM-DD[ HH:MM[:SS]]）")


def parse_rollout(path: str, window: tuple[datetime, datetime] | None = None) -> Session | None:
    """解析单个 rollout 文件；window 内无消耗的会话返回 None。"""
    uuids = UUID_RE.findall(os.path.basename(path))
    if not uuids:
        return None
    rec = Session(file=path, sid=uuids[0], uuids=uuids)
    per_model = defaultdict(lambda: [0, 0, 0, 0])
    current_model = "unknown"
    try:
        fh = open(path, errors="replace")
    except OSError:
        return None
    with fh:
        for line in fh:
            tag = line[:200]
            try:
                if '"session_meta"' in tag:
                    p = json.loads(line).get("payload", {})
                    rec.start = p.get("timestamp") or rec.start
                    rec.cwd = p.get("cwd")
                    ts = p.get("thread_source")
                    rec.type = TYPE_SHORT.get(ts, ts)
                    if len(uuids) >= 2 and ts == "subagent":
                        rec.sid = uuids[1]
                    src = p.get("source")
                    if isinstance(src, dict):
                        spawn = (src.get("subagent") or {}).get("thread_spawn") or {}
                        if spawn:
                            rec.parent = spawn.get("parent_thread_id") or uuids[0]
                            nick = spawn.get("agent_nickname") or "?"
                            role = spawn.get("agent_role") or spawn.get("agent_path") or ""
                            rec.agent = f"{nick}({role})" if role else nick
                elif '"turn_context"' in tag:
                    mm = json.loads(line).get("payload", {}).get("model")
                    if mm:
                        current_model = mm
                elif '"token_count"' in tag:
                    obj = json.loads(line)
                    info = obj.get("payload", {}).get("info") or {}
                    tl = to_local(obj.get("timestamp"))
                    if window is not None:
                        ws, we = window
                        if tl is None or not (ws <= tl <= we):
                            continue
                    if tl:
                        if rec.first_local is None or tl < rec.first_local:
                            rec.first_local = tl
                        if rec.last_local is None or tl > rec.last_local:
                            rec.last_local = tl
                    t = info.get("total_token_usage")
                    if t:
                        rec.final_total = [t.get("input_tokens", 0),
                                           t.get("cached_input_tokens", 0),
                                           t.get("output_tokens", 0)]
                    l = info.get("last_token_usage")
                    if l:
                        slot = per_model[current_model]
                        slot[0] += max(0, l.get("input_tokens", 0))
                        slot[1] += max(0, l.get("cached_input_tokens", 0))
                        slot[2] += max(0, l.get("output_tokens", 0))
                        slot[3] += max(0, l.get("reasoning_output_tokens", 0))
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue
    active = {k: v for k, v in per_model.items() if sum(v) > 0}
    if not active:
        return None
    rec.models = dict(active)
    rec.primary_model = max(active, key=lambda k: sum(active[k][:3]))
    rec.multi_model = len(active) > 1
    return rec


def collect(sessions_dir: str, since: datetime, until: datetime,
            archive_dir: str | None = None, raw: bool = False) -> list[Session]:
    """扫描日期范围内的 rollout 文件并解析；raw=True 时不合并同 ID 分页文件。"""
    days = []
    d = since.date()
    while d <= until.date():
        days.append(d.strftime("%Y/%m/%d"))
        d += timedelta(days=1)
    paths = []
    for day in days:
        paths += glob.glob(os.path.join(sessions_dir, day, "rollout-*.jsonl"))
    if archive_dir:
        paths += glob.glob(os.path.join(archive_dir, "rollout-*.jsonl"))
    recs = []
    for p in sorted(set(paths)):
        r = parse_rollout(p, window=(since, until))
        if not r:
            continue
        if raw:
            r.sid = r.uuids[-1]              # 每个文件一行，末位 UUID 区分分页
        recs.append(r)
    if raw:
        return recs
    merged: dict[str, Session] = {}
    for r in recs:
        old = merged.get(r.sid)
        if not old:
            merged[r.sid] = r
            continue
        for mname, v in r.models.items():
            slot = old.models.setdefault(mname, [0, 0, 0, 0])
            for i in range(4):
                slot[i] += v[i]
        old.parent = old.parent or r.parent
        old.agent = old.agent or r.agent
        old.multi_model = len(old.models) > 1
        old.primary_model = max(old.models, key=lambda k: sum(old.models[k][:3]))
    return list(merged.values())
