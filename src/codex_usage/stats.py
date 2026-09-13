"""统计聚合：token 汇总、成本折算、过滤器、时间分组。"""

import os
import re
from collections import defaultdict
from datetime import datetime

from .parser import Session
from .pricing import default_service_tier, model_cost


def _cost_by_tier(rec: Session, mname: str, slot: list[int], pricing: dict,
                  config_tier: str) -> float | None:
    """该模型成本：有档位明细就逐档计价（priority/Fast 与标准价不同），否则整块计价。

    无价返回 None（调用方按 $0 计并标 *）。`unknown` 档由定价层按 config.toml 的
    service_tier 处理，所以这里把档位原值原样传下去。
    """
    tiers = (rec.tiers or {}).get(mname)
    if not tiers:
        return model_cost(pricing, mname, slot[0] - slot[1], slot[1], slot[2])
    total, priced = 0.0, True
    for tier, tslot in tiers.items():
        c = model_cost(pricing, mname, tslot[0] - tslot[1], tslot[1], tslot[2],
                       tier=tier, config_tier=config_tier)
        if c is None:
            priced = False
        else:
            total += c
    return total if priced else None


def rec_tokens(rec: Session) -> tuple[int, int, int]:
    """(毛输入, 缓存读, 输出)"""
    tot = [0, 0, 0]
    for v in rec.models.values():
        for i in range(3):
            tot[i] += v[i]
    return tot[0], tot[1], tot[2]


def rec_cost(rec: Session, pricing: dict) -> tuple[float, bool]:
    """(成本[无定价按 $0], 是否全部模型有定价)"""
    cfg = default_service_tier()
    total, known = 0.0, True
    for mname, v in rec.models.items():
        c = _cost_by_tier(rec, mname, v, pricing, cfg)
        if c is None:
            known = False
        else:
            total += c
    return total, known


def rec_calls(rec: Session) -> int:
    """API 调用次数（token_count 轮次）。"""
    return sum(v[4] for v in rec.models.values())


def aggregate_models(recs: list[Session], pricing: dict) -> dict[str, list]:
    """聚合一组会话 → {model: [net, cached, out, calls, cost, known, nsess]}，按会话去重计数。"""
    agg: dict[str, list] = {}
    cfg = default_service_tier()
    for r in recs:
        seen = set()
        for mname, v in r.models.items():
            c = _cost_by_tier(r, mname, v, pricing, cfg)
            a = agg.setdefault(mname, [0, 0, 0, 0, 0.0, True, 0])
            a[0] += v[0] - v[1]
            a[1] += v[1]
            a[2] += v[2]
            a[3] += v[4]
            a[4] += c or 0.0
            a[5] = a[5] and (c is not None)
            if mname not in seen:
                a[6] += 1
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
        # 会话行（合并后）的 sid 是线程本体；`--raw` 下每页的 sid 取文件名末位 UUID，
        # 所以过滤要同时认文件名里的任意 UUID，否则 `--raw --session <首 UUID>`
        # 选不到分页续页（实测分页会话占窗口用量 7.88%）。
        def _hit(r: Session) -> bool:
            return r.sid.startswith(session) or any(u.startswith(session) for u in r.uuids)

        if family_mode:
            recs = [r for r in recs if _hit(r) or (r.parent or "").startswith(session)]
        else:
            recs = [r for r in recs if _hit(r)]
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
