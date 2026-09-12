"""命令行入口。

语义约定：
  --by-xxx      聚合维度，决定行粒度（--by-day 天 / --by-model 模型）
  --xxx 值      过滤器（--type/--model/--session/--parent/--since/--until/--archived）
  --family      家族结构：主线程+其子代理成树，带家族小计（可与聚合维度组合）
  --raw         实体降为文件粒度（分页/多副本文件不合并）
  --chart       图表渲染（pie/bar/area/line），数据来自聚合维度；--metric 选指标
  无 --by-*     行 = 实体（会话或文件）明细
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime

from . import __version__, config, stats
from .parser import collect, parse_time_arg
from .pricing import load_pricing
from .render import charts, tables

KNOWN_FLAGS = {"--since", "--until", "--by-day", "--family", "--raw", "--by-model",
               "--type", "--parent", "--session", "--model", "--archived", "--json",
               "--chart", "--metric", "--help"}


def _fix_single_dash(argv: list[str]) -> list[str]:
    """容错：单横线长参数（-by-model）纠正为双横线。"""
    fixed = []
    for a in argv:
        if re.fullmatch(r"-[a-zA-Z][a-zA-Z-]+", a) and "--" + a[1:] in KNOWN_FLAGS:
            print(f"提示: '{a}' 已按 '--{a[1:]}' 处理（长参数需要双横线）", file=sys.stderr)
            fixed.append("--" + a[1:])
        else:
            fixed.append(a)
    return fixed


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="codex-usage",
                                 description="Codex 按会话/子代理/天/模型用量与成本（本地 rollout 解析）")
    ap.add_argument("--since", help='过滤: 起始时间 "YYYY-MM-DD[ HH:MM[:SS]]"（默认今天 00:00）')
    ap.add_argument("--until", help="过滤: 结束时间（默认今天 23:59:59）")
    ap.add_argument("--by-day", action="store_true", help="聚合: 按天")
    ap.add_argument("--by-model", action="store_true", help="聚合: 按模型")
    ap.add_argument("--family", action="store_true", help="结构: 主线程+子代理家族树，带家族小计")
    ap.add_argument("--raw", action="store_true", help="实体: 文件粒度（分页/多副本文件不合并）")
    ap.add_argument("--chart", choices=("pie", "bar", "area", "line"),
                    help="图表: pie|bar|area|line（数据来自聚合维度）")
    ap.add_argument("--metric", choices=charts.METRICS, default="cost",
                    help="图表指标: cost|input|cache|output|total（默认 cost）")
    ap.add_argument("--type", dest="typ", help="过滤: user|subagent|guardian|voice|handoff|agent")
    ap.add_argument("--parent", help="过滤: 该父线程(前缀)及其子代理")
    ap.add_argument("--session", help="过滤: 该会话(前缀)；--family 下等同 --parent")
    ap.add_argument("--model", help="过滤: 模型名子串（会话与行双重过滤）")
    ap.add_argument("--archived", action="store_true", help="过滤: 含 archived_sessions")
    ap.add_argument("--json", action="store_true", help="输出: JSON（会话级记录，含按模型明细）")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return ap


def _emit_json(recs, pricing):
    for r in recs:
        gin, cached, out = stats.rec_tokens(r)
        cost, known = stats.rec_cost(r, pricing)
        d, t = stats.fmt_dt(r)
        print(json.dumps({
            "date": d, "time": t, "session_id": r.sid, "type": r.type,
            "agent": r.agent, "parent": r.parent, "cwd": r.cwd,
            "first_ts": r.first_local.isoformat() if r.first_local else None,
            "last_ts": r.last_local.isoformat() if r.last_local else None,
            "models": {m: {"input_gross": v[0], "cached": v[1], "output": v[2],
                           "reasoning": v[3]} for m, v in r.models.items()},
            "input_net": gin - cached, "cache_read": cached, "output": out,
            "cost_usd_known": round(cost, 4), "pricing_full": known,
            "last_cumulative_total": r.final_total,
        }, ensure_ascii=False))


def _day_series(recs, pricing):
    """按天聚合 → ({day: [net,cached,out,cost]}, {day: known})"""
    agg = defaultdict(lambda: [0, 0, 0, 0.0, True])
    for r in recs:
        d, _ = stats.fmt_dt(r)
        gin, ca, out = stats.rec_tokens(r)
        cost, known = stats.rec_cost(r, pricing)
        a = agg[d]
        a[0] += gin - ca; a[1] += ca; a[2] += out
        a[3] += cost; a[4] = a[4] and known
    return agg


def _chart(args, recs, pricing):
    if args.family:
        raise SystemExit("--chart 与 --family 不组合（图表按聚合维度渲染）")
    metric = args.metric
    unit = "USD" if metric == "cost" else "tokens"
    title_metric = charts.METRIC_LABEL[metric]

    if args.chart == "pie":
        if args.by_day:
            raise SystemExit("饼图只按模型聚合，请去掉 --by-day")
        agg = stats.aggregate_models(recs, pricing)
        print(charts.chart_pie(agg, metric))
        return

    if args.chart == "bar":
        if args.by_day and args.by_model:
            day_agg = _day_series(recs, pricing)
            days = sorted(day_agg)
            models = stats.aggregate_models(recs, pricing)
            series = {}
            for m in models:
                per_model_day = defaultdict(float)
                for r in recs:
                    d, _ = stats.fmt_dt(r)
                    if m in r.models:
                        v = r.models[m]
                        val = {"cost": None, "input": v[0] - v[1], "cache": v[1],
                               "output": v[2], "total": sum(v[:3])}[metric]
                        if metric == "cost":
                            from .pricing import model_cost
                            val = model_cost(pricing, m, v[0] - v[1], v[1], v[2]) or 0.0
                        per_model_day[d] += val or 0.0
                series[m] = [round(per_model_day.get(d, 0), 4) for d in days]
            print(charts.chart_bar([d[5:] for d in days], series, stacked=True,
                                   title=f"每天{title_metric}·堆叠"))
        elif args.by_day:
            agg = _day_series(recs, pricing)
            labels = [d[5:] for d in sorted(agg)]
            vals = [round(charts.metric_of([a[0], a[1], a[2], a[3]], metric), 4)
                    for a in (agg[d] for d in sorted(agg))]
            print(charts.chart_bar(labels, {title_metric: vals}, stacked=False,
                                   title=f"每天{title_metric}"))
        else:
            agg = stats.aggregate_models(recs, pricing)
            labels = sorted(agg, key=lambda m: -charts.metric_of(agg[m], metric))
            vals = [round(charts.metric_of(agg[m], metric), 4) for m in labels]
            print(charts.chart_bar(labels, {title_metric: vals}, stacked=False,
                                   title=f"各模型{title_metric}"))
        return

    # area / line：按天趋势
    agg = _day_series(recs, pricing)
    days = sorted(agg)
    labels = [d[5:] for d in days]
    if args.by_model:
        models = stats.aggregate_models(recs, pricing)
        series = {}
        for m in models:
            per_model_day = defaultdict(float)
            for r in recs:
                d, _ = stats.fmt_dt(r)
                if m in r.models:
                    v = r.models[m]
                    from .pricing import model_cost
                    val = (model_cost(pricing, m, v[0] - v[1], v[1], v[2]) or 0.0) if metric == "cost" \
                        else {"input": v[0] - v[1], "cache": v[1], "output": v[2],
                              "total": sum(v[:3])}[metric]
                    per_model_day[d] += val
            series[m] = [round(per_model_day.get(d, 0), 4) for d in days]
        print(charts.chart_series(args.chart, labels, series,
                                  title=f"每天{title_metric}·按模型"))
    else:
        vals = [round(charts.metric_of([a[0], a[1], a[2], a[3]], metric), 4)
                for a in (agg[d] for d in days)]
        print(charts.chart_series(args.chart, labels, {title_metric: vals},
                                  title=f"每天{title_metric}"))


def main():
    sys.argv = [sys.argv[0]] + _fix_single_dash(sys.argv[1:])
    args = build_parser().parse_args()

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    since = parse_time_arg(args.since) if args.since else today
    until = parse_time_arg(args.until, end=True) if args.until else today.replace(hour=23, minute=59, second=59)
    if since > until:
        raise SystemExit("--since 晚于 --until")

    recs = collect(config.sessions_dir(), since, until,
                   archive_dir=config.archive_dir() if args.archived else None,
                   raw=args.raw)
    recs = stats.apply_filters(recs, typ=args.typ, session=args.session, model=args.model,
                               parent=args.parent, family_mode=args.family)

    if args.json:
        _emit_json(recs, load_pricing())
        return
    if not recs:
        print("该范围内没有会话。")
        return
    if args.chart:
        _chart(args, recs, load_pricing())
        return

    pricing = load_pricing()
    if args.by_day and not args.family:
        tables.view_by_day(recs, pricing, args.by_model)
    elif args.by_model and not args.family:
        tables.view_models(recs, pricing)
    elif args.family:
        tables.view_families(recs, pricing, args.by_model, args.by_day)
    else:
        tables.view_flat(recs, pricing)


if __name__ == "__main__":
    main()
