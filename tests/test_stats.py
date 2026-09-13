"""统计聚合测试：token 汇总、成本折算（含无定价模型）、模型聚合与不变量。"""

from datetime import datetime

from codex_usage.parser import Session, collect
from codex_usage.pricing import load_pricing
from codex_usage import stats


def test_aggregate_models(env):
    pricing = load_pricing(env["pricing"])
    recs = collect(env["sessions"], datetime(2026, 9, 10), datetime(2026, 9, 11, 23, 59, 59))
    agg = stats.aggregate_models(recs, pricing)
    # luna: 会话A(净3000/缓存25000/出1000, 2轮) + 分页两页(净210/缓存4000/出61, 各1轮)
    a = agg["gpt-5.6-luna"]
    assert a[0] == 3000 + 210
    assert a[1] == 25000 + 4000
    assert a[2] == 1000 + 61
    assert a[3] == 4                                         # 调用次数 = token_count 轮次
    # 成本：(3210*10 + 29000*1 + 1061*50)/1e6
    assert abs(a[4] - (3210 * 10 + 29000 * 1 + 1061 * 50) / 1e6) < 1e-9
    assert a[5] is True
    assert a[6] == 2                                         # 会话数（A + 分页合并）


def test_unpriced_model_counted_at_zero(env):
    pricing = load_pricing(env["pricing"])
    recs = collect(env["sessions"], datetime(2026, 9, 11), datetime(2026, 9, 11, 23, 59, 59))
    agg = stats.aggregate_models(recs, pricing)
    a = agg["gpt-mystery"]
    assert a[0] == 300 and a[1] == 1000 and a[2] == 50    # token 照常统计
    assert a[3] == 1                                       # 调用 1 次
    assert a[4] == 0.0                                     # 成本按 $0
    assert a[5] is False                                   # 标注无定价


def test_rec_cost_math(env):
    pricing = load_pricing(env["pricing"])
    recs = collect(env["sessions"], datetime(2026, 9, 10), datetime(2026, 9, 10, 23, 59, 59))
    user = [r for r in recs if r.type == "user" and r.primary_model == "gpt-5.6-luna"]
    cost, known = stats.rec_cost(user[0], pricing)
    # A 会话 luna: 净3000/缓存25000/出1000 → (3000*10 + 25000*1 + 1000*50)/1e6 = 0.105
    assert abs(cost - 0.105) < 1e-9
    assert known is True


def test_totals_invariant_across_aggregations(env):
    """不变量：按会话、按模型、按天三种聚合的 (净输入, 缓存读, 输出, 调用) 合计一致。"""
    pricing = load_pricing(env["pricing"])
    recs = collect(env["sessions"], datetime(2026, 9, 10), datetime(2026, 9, 11, 23, 59, 59))

    def totals(rs):
        t = [0, 0, 0, 0]
        for r in rs:
            gin, ca, out = stats.rec_tokens(r)
            t[0] += gin - ca
            t[1] += ca
            t[2] += out
            t[3] += stats.rec_calls(r)
        return t

    by_session = totals(recs)
    agg = stats.aggregate_models(recs, pricing)
    by_model = [sum(a[i] for a in agg.values()) for i in range(4)]
    by_day = [0, 0, 0, 0]
    for rs in stats.group_by_day(recs).values():
        for i, v in enumerate(totals(rs)):
            by_day[i] += v
    assert by_session == by_model == by_day


def _rec(model, slots_by_tier, pricing):
    """构造仅用于计价的最小 Session。"""
    rec = Session(file="f", sid="s", uuids=["u"])
    total = [0, 0, 0, 0, 0]
    for slot in slots_by_tier.values():
        for i in range(5):
            total[i] += slot[i]
    rec.models = {model: total}
    rec.tiers = {model: slots_by_tier}
    return rec


def test_rec_cost_applies_tier_multiplier():
    """priority/Fast 档按官方倍率计价，成本必须高于同量标准档（astra 官方 2.0×）。"""
    from codex_usage.pricing import load_pricing
    from codex_usage import stats

    pricing = load_pricing()
    std = _rec("gpt-6-astra", {"standard": [1000, 0, 100, 0, 1]}, pricing)
    mix = _rec("gpt-6-astra", {"standard": [500, 0, 50, 0, 1],
                               "priority": [500, 0, 50, 0, 1]}, pricing)
    std_cost, std_known = stats.rec_cost(std, pricing)
    mix_cost, mix_known = stats.rec_cost(mix, pricing)
    assert std_known and mix_known
    assert mix_cost > std_cost                      # Fast 档加成
    assert mix_cost < std_cost * 2                  # 但只有一半用量在 Fast 档


def test_rec_cost_falls_back_when_no_tiers():
    """没有档位明细（老数据/异常）时仍能整块计价，不报错。"""
    from codex_usage.pricing import load_pricing
    from codex_usage import stats

    pricing = load_pricing()
    rec = Session(file="f", sid="s", uuids=["u"])
    rec.models = {"gpt-6-astra": [1000, 0, 100, 0, 1]}
    cost, known = stats.rec_cost(rec, pricing)
    assert known and cost > 0
