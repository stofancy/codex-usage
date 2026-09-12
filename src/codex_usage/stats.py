"""统计聚合：token 汇总、成本折算、过滤器、时间分组。"""

import os
import re
from collections import defaultdict
from datetime import datetime

from .parser import Session
from .pricing import model_cost


def rec_tokens(rec: Session) -> tuple[int, int, int]:
    """(毛输入, 缓存读, 输出)"""
    tot = [0, 0, 0]
    for v in rec.models.values():
        for i in range(3):
            tot[i] += v[i]
    return tot[0], tot[1], tot[2]


def rec_cost(rec: Session, pricing: dict) -> tuple[float, bool]:
    """(成本[无定价按 $0], 是否全部模型有定价)"""
    total, known = 0.0, True
    for mname, v in rec.models.items():
        c = model_cost(pricing, mname, v[0] - v[1], v[1], v[2])
        if c is None:
            known = False
        else:
            total += c
    return total, known


def aggregate_models(recs: list[Session], pricing: dict) -> dict[str, list]:
    """聚合一组会话 → {model: [net, cached, out, cost, known, nsess]}，按会话去重计数。"""
    agg: dict[str, list] = {}
    for r in recs:
        seen = set()
        for mname, v in r.models.items():
            c = model_cost(pricing, mname, v[0] - v[1], v[1], v[2])
            a = agg.setdefault(mname, [0, 0, 0, 0.0, True, 0])
            a[0] += v[0] - v[1]; a[1] += v[1]; a[2] += v[2]
            a[3] += c or 0.0
            a[4] = a[4] and (c is not None)
            if mname not in seen:
                a[5] += 1
                seen.add(mname)
    return agg


def unknown_models(recs: list[Session], pricing: dict) -> list[str]:
    return sorted({m for r in recs for m in r.models if m not in pricing})


def group_by_day(recs: list[Session]) -> dict[str, list[Session]]:
    groups: dict[str, list[Session]] = defaultdict(list)
    for r in recs:
        groups[fmt_dt(r)[0]].append(r)
    return groups


def sort_key(rec: Session):
    return (rec.first_local or datetime.min, rec.file)


def apply_filters(recs: list[Session], *, typ: str | None = None, session: str | None = None,
                  model: str | None = None, parent: str | None = None,
                  family_mode: bool = False) -> list[Session]:
    """应用 --type/--session/--model/--parent 过滤；family_mode 下 --session 等同 --parent。"""
    if typ:
        recs = [r for r in recs if r.type == typ]
    if session:
        if family_mode:
            recs = [r for r in recs if r.sid.startswith(session)
                    or (r.parent or "").startswith(session)]
        else:
            recs = [r for r in recs if r.sid.startswith(session)]
    if model:
        recs = [r for r in recs if any(model in m for m in r.models)]
        for r in recs:                    # 模型维度过滤：仅保留匹配模型的用量
            r.models = {m: v for m, v in r.models.items() if model in m}
            r.multi_model = len(r.models) > 1
            r.primary_model = max(r.models, key=lambda k: sum(r.models[k][:3]))
    if parent:
        recs = [r for r in recs if (r.parent or "").startswith(parent)
                or r.sid.startswith(parent)]
    return recs


def fmt_dt(rec: Session) -> tuple[str, str]:
    """(YYYY-MM-DD, HH:MM)：优先活动起点，回退文件名时间。"""
    fl = rec.first_local
    if fl:
        return fl.strftime("%Y-%m-%d"), fl.strftime("%H:%M")
    m = re.match(r"rollout-(\d{4}-\d{2}-\d{2})T(\d{2}-\d{2})", os.path.basename(rec.file))
    return (m.group(1), m.group(2).replace("-", ":")) if m else ("?", "?")
