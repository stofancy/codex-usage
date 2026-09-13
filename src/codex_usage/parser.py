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
    # model -> [gross_in, cached, out, reasoning, calls]
    models: dict[str, list[int]] = field(default_factory=dict)
    # model -> 计量档位（thread_settings_applied 的 service_tier 原值；没出现过则 "unknown"）
    #         -> [gross_in, cached, out, reasoning, calls]，用于 priority/Fast 档倍率定价
    tiers: dict[str, dict[str, list[int]]] = field(default_factory=dict)
    # 旧口径（逐轮 last_token_usage 累加，毛输入+输出）对照值：与累计差分交叉校验
    delta_sum: int = 0
    # 诊断：累计值下降（上下文压缩重置）次数、缺 total_token_usage 回退次数
    resets: int = 0
    fallbacks: int = 0
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
    """解析 --since/--until。

    支持 "2026-09-12[ 16:10[:23]]"（T 可代空格）与紧凑 "20260912[-16[10[23]]]"
    （分隔符可用 - _ 空格 . T，时间也可写 16:10[:23]）；缺省部分 since 补 0，
    until 补满（23:59:59 / 分秒 59）。
    """
    s = s.strip()
    # 不用 %Y%m%d：它会把 "2026091"（7 位）宽松解析成 2026-09-01；
    # 8 位纯日期由下面的紧凑分支严格处理
    for f in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
              "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, f)
            if end:                             # 与紧凑格式一致：缺省部分补满
                if "%S" not in f:
                    dt = dt.replace(second=59)
                if "%M" not in f:
                    dt = dt.replace(minute=59)
                if "%H" not in f:
                    dt = dt.replace(hour=23)
            return dt
        except ValueError:
            continue
    m = re.match(r"(\d{8})(?:[-_ T.]?(\d{2}:\d{2}(?::\d{2})?)?(\d{6}|\d{4}|\d{2})?)?$", s)
    if m:
        y, mo, dd = int(m.group(1)[:4]), int(m.group(1)[4:6]), int(m.group(1)[6:8])
        h = mi = se = 0
        if m.group(2):                      # HH[:MM[:SS]]（MM/SS 均可省略）
            g = m.group(2)
            h = int(g[:2])
            mi = int(g[3:5]) if len(g) > 2 else 0
            se = int(g[6:8]) if len(g) > 5 else 0
            prec = 3 if len(g) > 5 else (2 if len(g) > 2 else 1)
        elif m.group(3):                    # 紧凑 HH[MM[SS]]
            t = m.group(3)
            h = int(t[:2])
            mi = int(t[2:4]) if len(t) >= 4 else 0
            se = int(t[4:6]) if len(t) >= 6 else 0
            prec = len(t) // 2
        else:                               # 纯 YYYYMMDD
            prec = 0
        if end:
            if prec < 3:
                se = 59
            if prec < 2:
                mi = 59
            if prec < 1:
                h = 23
        try:
            return datetime(y, mo, dd, h, mi, se)
        except ValueError:
            pass
    raise SystemExit(f"无法解析时间: {s}（支持 2026-09-12[ 16:10[:23]] 或 20260912[-16[10[23]]]）")


def _token(d, key: str) -> int:
    """从 token 分量字典里取非负整数（缺失/None/非数字都按 0）。"""
    try:
        return max(0, int(d.get(key, 0) or 0))
    except (TypeError, ValueError):
        return 0


def parse_rollout(path: str, window: tuple[datetime, datetime] | None = None) -> Session | None:
    """解析单个 rollout 文件；window 内无消耗的会话返回 None。

    计量口径：以 `token_count.payload.info.total_token_usage` 的**增量**为准
    （当前累计 − 上一累计），按当时 `turn_context` 的模型归因。这样：
      * 重复事件/重放的父历史前缀增量为 0，天然不重复计数（实测同一文件里
        逐轮 last 累加会比最终累计高 10.1%，53% 的文件存在重复累计值）；
      * 上下文压缩导致累计值下降时，该轮回退用 last_token_usage；
      * 缺 total_token_usage 时同样回退 last_token_usage，不丢数据。
    `last_token_usage` 的累加值保留在 `delta_sum` 供交叉校验。
    """
    uuids = UUID_RE.findall(os.path.basename(path))
    if not uuids:
        return None
    rec = Session(file=path, sid=uuids[0], uuids=uuids)
    per_model: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0])
    prev_total: list[int] | None = None          # 上一事件的累计快照
    current_model = "unknown"
    current_tier = "unknown"                     # 没有任何 thread_settings 时按 unknown
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
                elif '"thread_settings_applied"' in tag:
                    # 每次线程设置变更带 service_tier（default / priority / fast …）；
                    # 顺带用其中的 model 兜底 turn_context 缺失的会话。
                    st = (json.loads(line).get("payload", {}) or {}).get("thread_settings") or {}
                    tier = st.get("service_tier")
                    if tier:
                        current_tier = str(tier)
                    if st.get("model") and current_model == "unknown":
                        current_model = st["model"]
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
                    last_obj = info.get("last_token_usage")
                    last_u = last_obj or {}
                    last_v = [_token(last_u, "input_tokens"), _token(last_u, "cached_input_tokens"),
                              _token(last_u, "output_tokens"),
                              _token(last_u, "reasoning_output_tokens")]
                    if last_v[0] or last_v[2]:                  # 旧口径对照（毛输入 + 输出）
                        rec.delta_sum += last_v[0] + last_v[2]
                    total = info.get("total_token_usage")
                    if total:
                        cur = [_token(total, "input_tokens"), _token(total, "cached_input_tokens"),
                               _token(total, "output_tokens"),
                               _token(total, "reasoning_output_tokens")]
                        rec.final_total = cur[:3]
                        if prev_total is None:
                            # 首帧累计值可能整块是**继承的父线程历史**（实测有文件首帧
                            # 14,051,760 而 last 全 0）：只计它自己的增量，否则会虚高数十倍。
                            delta = last_v if last_obj is not None else cur
                        else:
                            inc = [c - p for c, p in zip(cur, prev_total)]
                            if any(x < 0 for x in inc):
                                rec.resets += 1                 # 压缩重置：累计值回落
                                delta = (last_v if last_obj is not None
                                         else [max(0, x) for x in inc])
                            elif last_obj is not None and any(last_v):
                                # 正常帧「累计增量 == last」；跳升远大于 last 说明中间插入了
                                # 继承历史，用 last 封顶（分量为 0 时仍取增量，不少算）。
                                delta = [min(max(0, x), cap) if cap else max(0, x)
                                         for x, cap in zip(inc, last_v)]
                            else:
                                delta = [max(0, x) for x in inc]
                        prev_total = cur
                    else:
                        rec.fallbacks += 1                       # 缺累计值：回退逐轮增量
                        delta = last_v
                    if any(delta):
                        slot = per_model[current_model]
                        slot[4] += 1                             # 一次 API 调用（有效轮次）
                        for i in range(4):
                            slot[i] += max(0, delta[i])
                        tslot = rec.tiers.setdefault(current_model, {}).setdefault(
                            current_tier, [0, 0, 0, 0, 0])
                        tslot[4] += 1
                        for i in range(4):
                            tslot[i] += max(0, delta[i])
            except (json.JSONDecodeError, AttributeError, TypeError):
                continue
    # 只保留有 token 消耗的模型槽位：calls 槽不计入，否则「无 turn_context + 零 token」
    # 的 token_count 事件会带出一个全 0 的 unknown 模型行（旧版口径按 token 分量过滤）
    active = {k: v for k, v in per_model.items() if sum(v[:4]) > 0}
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
        # sessions/ 与 archived_sessions/ 可能同时保存同一会话（文件名 UUID 相同）：
        # 以 sessions/ 为准，否则按 sid 合并会把同一份用量累加两次。
        active_keys = {tuple(UUID_RE.findall(os.path.basename(p))) for p in paths}
        for p in glob.glob(os.path.join(archive_dir, "rollout-*.jsonl")):
            if tuple(UUID_RE.findall(os.path.basename(p))) in active_keys:
                continue
            paths.append(p)
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
            slot = old.models.setdefault(mname, [0, 0, 0, 0, 0])
            for i in range(5):
                slot[i] += v[i]
        for mname, tiers in r.tiers.items():     # 分页文件同样要合并档位明细，否则
            dest = old.tiers.setdefault(mname, {})   # tiers 合计会小于 models（实测差 4.81M 毛输入）
            for tname, tslot in tiers.items():
                dslot = dest.setdefault(tname, [0, 0, 0, 0, 0])
                for i in range(5):
                    dslot[i] += tslot[i]
        old.delta_sum += r.delta_sum
        old.resets += r.resets
        old.fallbacks += r.fallbacks
        old.parent = old.parent or r.parent
        old.agent = old.agent or r.agent
        old.multi_model = len(old.models) > 1
        old.primary_model = max(old.models, key=lambda k: sum(old.models[k][:3]))
    return list(merged.values())
