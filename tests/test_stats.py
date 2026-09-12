"""统计聚合测试：token 汇总、成本折算（含无定价模型）、模型聚合与不变量。"""

from datetime import datetime

from codex_usage.parser import collect
from codex_usage.pricing import load_pricing
from codex_usage import stats


def test_aggregate_models(env):
    pricing = load_pricing(env["pricing"])
    recs = collect(env["sessions"], datetime(2026, 9, 10), datetime(2026, 9, 11, 23, 59, 59))
    agg = stats.aggregate_models(recs, pricing)
    # luna: 会话A(净3000/缓存25000/出1000) + 分页两页(净210/缓存4000/出61)
    a = agg["gpt-5.6-luna"]
    assert a[0] == 3000 + 210
    assert a[1] == 25000 + 4000
    assert a[2] == 1000 + 61
    # 成本：(3210*10 + 29000*1 + 1061*50)/1e6
    assert abs(a[3] - (3210 * 10 + 29000 * 1 + 1061 * 50) / 1e6) < 1e-9
    assert a[4] is True


def test_unpriced_model_counted_at_zero(env):
    pricing = load_pricing(env["pricing"])
    recs = collect(env["sessions"], datetime(2026, 9, 11), datetime(2026, 9, 11, 23, 59, 59))
    agg = stats.aggregate_models(recs, pricing)
    a = agg["gpt-mystery"]
    assert a[0] == 300 and a[1] == 1000 and a[2] == 50    # token 照常统计
    assert a[3] == 0.0                                     # 成本按 $0
    assert a[4] is False                                   # 标注无定价


def test_rec_cost_math(env):
    pricing = load_pricing(env["pricing"])
    recs = collect(env["sessions"], datetime(2026, 9, 10), datetime(2026, 9, 10, 23, 59, 59))
    user = [r for r in recs if r.type == "user" and r.primary_model == "gpt-5.6-luna"]
    cost, known = stats.rec_cost(user[0], pricing)
    # A 会话 luna: 净3000/缓存25000/出1000 → (3000*10 + 25000*1 + 1000*50)/1e6 = 0.105
    assert abs(cost - 0.105) < 1e-9
    assert known is True


def test_totals_invariant_across_aggregations(env):
    """不变量：按会话、按模型、按天三种聚合的 (净输入, 缓存读, 输出) 合计一致。"""
    pricing = load_pricing(env["pricing"])
    recs = collect(env["sessions"], datetime(2026, 9, 10), datetime(2026, 9, 11, 23, 59, 59))

    def totals(rs):
        t = [0, 0, 0]
        for r in rs:
            gin, ca, out = stats.rec_tokens(r)
            t[0] += gin - ca; t[1] += ca; t[2] += out
        return t

    by_session = totals(recs)
    agg = stats.aggregate_models(recs, pricing)
    by_model = [sum(a[i] for a in agg.values()) for i in range(3)]
    by_day = [0, 0, 0]
    for rs in stats.group_by_day(recs).values():
        for i, v in enumerate(totals(rs)):
            by_day[i] += v
    assert by_session == by_model == by_day
