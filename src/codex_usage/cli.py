"""命令行入口。

语义约定：
  --by-xxx      聚合维度，决定行粒度（--by-day 天 / --by-model 模型）
  --xxx 值      过滤器（--type/--model/--session/--parent/--since/--until/--archived）
  --family      家族结构：主线程+其子代理成树，带家族小计（可与聚合维度组合）
  --raw         实体降为文件粒度（分页/多副本文件不合并）
  --chart       图表渲染（pie/bar/area/line），数据来自聚合维度；--metric 选指标
                （终端+image extras 出真图，--ascii/管道/未装依赖回退字符画）
  --schema      机器可读自描述（命令契约、字段、退出码的 JSON 版帮助）
  --doctor      环境自检（数据源、定价表、真图能力、终端档位）
  --update-pricing  唯一联网动作：从公开渠道刷新本地定价缓存（用户显式触发）
  无 --by-*     行 = 实体（会话或文件）明细

帮助入口：-h / --help / /? / -? / help
"""

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

from rich.console import Console

from . import __version__, config, selfdoc, stats
from .parser import collect, parse_time_arg
from .pricing import load_pricing, model_cost
from .render import charts, imgcharts, tables

KNOWN_FLAGS = {"--since", "--until", "--by-day", "--family", "--raw", "--by-model",
               "--type", "--parent", "--session", "--model", "--archived", "--json",
               "--chart", "--metric", "--ascii", "--schema", "--doctor",
               "--update-pricing", "--pricing-source", "--version", "--help"}


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
                                 description="Codex 按会话/子代理/天/模型用量与成本（本地 rollout 解析）",
                                 epilog=selfdoc.EPILOG,
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 add_help=False)
    ap.add_argument("-h", "--help", action="help", help="显示本帮助（/?、-?、help 等价）")
    ap.add_argument("--since",
                    help='过滤: 起始时间，支持 "2026-09-12 16:10:23" 或紧凑 "20260912-161023"、'
                         '"20260912-16"（缺省部分补 0，默认今天 00:00）')
    ap.add_argument("--until", help="过滤: 结束时间，格式同 --since（缺省部分补满，默认今天 23:59:59）")
    ap.add_argument("--by-day", action="store_true", help="聚合: 按天")
    ap.add_argument("--by-model", action="store_true", help="聚合: 按模型")
    ap.add_argument("--family", action="store_true", help="结构: 主线程+子代理家族树，带家族小计")
    ap.add_argument("--raw", action="store_true", help="实体: 文件粒度（分页/多副本文件不合并）")
    ap.add_argument("--chart", choices=("pie", "bar", "area", "line"),
                    help="图表: pie|bar|area|line（数据来自聚合维度）")
    ap.add_argument("--metric", choices=charts.METRICS, default="cost",
                    help="图表指标: cost|input|cache|output|total（默认 cost）")
    ap.add_argument("--ascii", action="store_true", help="图表: 强制字符画（默认终端下优先真图）")
    ap.add_argument("--type", dest="typ", help="过滤: user|subagent|guardian|voice|handoff|agent")
    ap.add_argument("--parent", help="过滤: 该父线程(前缀)及其子代理")
    ap.add_argument("--session", help="过滤: 该会话(前缀)；--family 下等同 --parent")
    ap.add_argument("--model", help="过滤: 模型名子串（会话与行双重过滤）")
    ap.add_argument("--archived", action="store_true", help="过滤: 含 archived_sessions")
    ap.add_argument("--json", action="store_true", help="输出: JSON（会话级记录，含按模型明细）")
    ap.add_argument("--schema", action="store_true",
                    help="自描述: 输出机器可读契约 JSON（选项、字段、语义、退出码）")
    ap.add_argument("--doctor", action="store_true",
                    help="自检: 报告数据源/定价表/真图能力/终端档位（配 --json 输出结构化）")
    ap.add_argument("--update-pricing", action="store_true",
                    help="定价: 从公开渠道拉取定价写入本地缓存（随后自动使用；默认 models.dev）")
    ap.add_argument("--pricing-source", choices=("models.dev", "litellm"), default="models.dev",
                    help="定价: --update-pricing 的数据源（默认 models.dev）")
    ap.add_argument("--version", action="version", version=f"%(prog)s {__version__}",
                    help="显示版本号")
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
                           "reasoning": v[3], "calls": v[4]} for m, v in r.models.items()},
            "input_net": gin - cached, "cache_read": cached, "output": out,
            "total_tokens": gin + out,  # 毛+输出 = 净+缓存+输出
            "calls": stats.rec_calls(r),
            "cost_usd_known": round(cost, 4), "pricing_full": known,
            "last_cumulative_total": r.final_total,
        }, ensure_ascii=False))


def _day_series(recs, pricing):
    """按天聚合 → {day: [net, cached, out, calls, cost, known]}（与 aggregate_models 槽位一致）"""
    agg = defaultdict(lambda: [0, 0, 0, 0, 0.0, True])
    for r in recs:
        d, _ = stats.fmt_dt(r)
        gin, ca, out = stats.rec_tokens(r)
        cost, known = stats.rec_cost(r, pricing)
        a = agg[d]
        a[0] += gin - ca
        a[1] += ca
        a[2] += out
        a[3] += stats.rec_calls(r)
        a[4] += cost
        a[5] = a[5] and known
    return agg


def _model_metric(mname: str, v: list, metric: str, pricing: dict) -> float:
    """单模型原始槽 [毛输入, 缓存读, 输出, 推理, 调用] → 图表指标值。

    total = 毛输入 + 输出（= 净输入 + 缓存读 + 输出）：毛输入已含缓存读，不能用 sum(v[:3])，
    否则缓存读被计两次（实测真实数据虚高 94%）。
    """
    if metric == "cost":
        return model_cost(pricing, mname, v[0] - v[1], v[1], v[2]) or 0.0
    return {"input": v[0] - v[1], "cache": v[1], "output": v[2], "total": v[0] + v[2]}[metric]


def _use_image(args) -> bool:
    """终端 + 装了 image extras + 未指定 --ascii（含 CODEX_USAGE_IMAGE_MODE=ascii）时用真图。"""
    if args.ascii or not sys.stdout.isatty() or imgcharts.image_mode() == "ascii":
        return False
    if imgcharts.available():
        return True
    print("提示: 未安装图片渲染依赖，图表回退字符画（装法: uv tool install "
          "'codex-usage[image]'，需 Python ≥3.12）", file=sys.stderr)
    return False


def _chart(args, recs, pricing):
    """图表入口：优先真图（终端 + image extras），渲染失败或不可用时回退字符画。"""
    if _use_image(args):
        try:
            _chart_draw(args, recs, pricing, imgcharts, lambda r: Console().print(r))
            return
        except Exception as e:            # 渲染问题不该让整个命令崩掉，降级到字符画
            print(f"提示: 真图渲染失败（{type(e).__name__}: {e}），已回退字符画", file=sys.stderr)
    _chart_draw(args, recs, pricing, charts, print)


def _chart_draw(args, recs, pricing, render, emit):
    metric = args.metric
    title_metric = charts.METRIC_LABEL[metric]

    if args.chart == "pie":
        agg = stats.aggregate_models(recs, pricing)
        emit(render.chart_pie(agg, metric))
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
                        per_model_day[d] += _model_metric(m, r.models[m], metric, pricing)
                series[m] = [round(per_model_day.get(d, 0), 4) for d in days]
            emit(render.chart_bar([d[5:] for d in days], series, stacked=True,
                                  title=f"每天{title_metric}·堆叠"))
        elif args.by_day:
            agg = _day_series(recs, pricing)
            labels = [d[5:] for d in sorted(agg)]
            vals = [round(charts.metric_of(agg[d], metric), 4) for d in sorted(agg)]
            emit(render.chart_bar(labels, {title_metric: vals}, stacked=False,
                                  title=f"每天{title_metric}"))
        else:
            agg = stats.aggregate_models(recs, pricing)
            labels = sorted(agg, key=lambda m: -charts.metric_of(agg[m], metric))
            vals = [round(charts.metric_of(agg[m], metric), 4) for m in labels]
            emit(render.chart_bar(labels, {title_metric: vals}, stacked=False,
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
                    per_model_day[d] += _model_metric(m, r.models[m], metric, pricing)
            series[m] = [round(per_model_day.get(d, 0), 4) for d in days]
        emit(render.chart_series(args.chart, labels, series,
                                 title=f"每天{title_metric}·按模型"))
    else:
        vals = [round(charts.metric_of(agg[d], metric), 4) for d in days]
        emit(render.chart_series(args.chart, labels, {title_metric: vals},
                                 title=f"每天{title_metric}"))


def main():
    try:
        _main()
    except BrokenPipeError:
        # 管道下游提前退出（如 | head）：屏蔽退出时 flush 的二次报错，按 SIGPIPE 惯例退出
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(141)


def _update_pricing(args) -> None:
    """--update-pricing：从公开渠道刷新本地定价缓存（唯一的联网动作，仅用户显式触发）。

    延迟导入：定价同步是可选路径，不该拖慢每次启动，也不该让整个 CLI 依赖它。
    """
    try:
        from .pricing import sync as sync_pricing
        info = sync_pricing(args.pricing_source, timeout=30.0)
    except Exception as e:
        raise SystemExit(f"定价更新失败（{type(e).__name__}: {e}）；可继续用内置定价表")
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
    else:
        print(f"定价已更新：{info.get('models', '?')} 个模型 → {info.get('path', '?')}"
              f"（来源 {info.get('source', args.pricing_source)}）")


def _main():
    argv = sys.argv[1:]
    if argv and argv[0] in ("/?", "-?", "help"):   # Windows 风格与子命令风格帮助入口
        argv = ["--help"]
    sys.argv = [sys.argv[0]] + _fix_single_dash(argv)
    args = build_parser().parse_args()

    if args.schema:                                # 自描述与自检先于数据扫描
        print(json.dumps(selfdoc.schema(build_parser()), ensure_ascii=False, indent=2))
        return
    if args.doctor:
        report = selfdoc.doctor()
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json
              else selfdoc.format_doctor(report))
        return
    if args.update_pricing:                        # 定价刷新先于数据扫描
        _update_pricing(args)
        return
    if args.chart:
        # 参数冲突先于数据扫描与依赖探测报出，避免无数据时静默通过
        if args.family:
            raise SystemExit("--chart 与 --family 不组合（图表按聚合维度渲染）")
        if args.chart == "pie" and args.by_day:
            raise SystemExit("饼图只按模型聚合，请去掉 --by-day")

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
