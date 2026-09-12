"""终端表格视图（rich 实现：CJK 宽字符精确对齐、颜色、无 TTY 自动去色）。

布局约定：所有表格的末 7 列固定为 净输入/缓存读/输出/总 tokens/调用/单次成本/成本，
行构造一律走 _metric_row（cells_before + 7 个数字），防止单元格数与列数错位——
rich 对超出的单元格会静默加宽表格，导致合计行数字跑到表头之外。
"""

import sys

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from ..parser import Session
from .. import stats

TYPE_STYLE = {"user": "", "subagent": "cyan", "guardian": "yellow",
              "voice": "magenta", "handoff": "blue", "agent": "green"}


def console() -> Console:
    # 非 TTY（管道/重定向）时给足宽度，避免 rich 按 80 列截断
    return Console(width=None if sys.stdout.isatty() else 250)


def _type_cell(t: str | None) -> Text:
    t = t or "?"
    style = TYPE_STYLE.get(t, "")
    return Text(t, style=style)


def _model_cell(m: str) -> Text:
    return Text(m, style="cyan")


def _note(rec: Session) -> str:
    if rec.type == "subagent":
        return rec.agent or "subagent"
    return (rec.parent or "")[:13]


def _acc() -> list:
    """累计器 [net, cached, out, calls, cost, known]，与 aggregate_models 槽位前 6 位一致。"""
    return [0, 0, 0, 0, 0.0, True]


def _merge_acc(acc: list, net: int, cached: int, out: int, calls: int, cost: float, known: bool):
    acc[0] += net; acc[1] += cached; acc[2] += out; acc[3] += calls
    acc[4] += cost; acc[5] = acc[5] and known


def _unit_cost_s(cost: float, calls: int, known: bool) -> str:
    if not calls:
        return "-"
    u = cost / calls
    s = f"${u:,.2f}" if u >= 1 else (f"${u:.4f}" if u >= 0.01 else f"${u:.6f}")
    return s + ("" if known else "*")


def _metric_row(tb: Table, cells_before: list, acc: list, style: str | None = None):
    """数字指标行：末 7 列为 净输入/缓存读/输出/总/调用/单次成本/成本（总=净+缓存+输出）。

    cells_before 为数字列之前的单元格（标签+留空），其长度 + 7 必须等于表格列数；
    不匹配说明调用方列布局写错了（rich 会静默加宽表格导致错位），直接断言拦截。
    """
    assert len(tb.columns) == len(cells_before) + 7, \
        f"列布局不匹配: 表格 {len(tb.columns)} 列 vs 前置 {len(cells_before)} + 7 数字列"
    net, cached, out, calls, cost, known = acc
    vals = [f"{net:,}", f"{cached:,}", f"{out:,}", f"{net + cached + out:,}",
            f"{calls:,}", _unit_cost_s(cost, calls, known),
            f"${cost:,.2f}" + ("" if known else "*")]
    tb.add_row(*cells_before, *(Text(v, style=style) for v in vals))


def _add_metric_columns(tb: Table):
    for col in ("净输入", "缓存读", "输出", "总 tokens", "调用", "单次成本", "成本"):
        tb.add_column(col, justify="right")


def print_unknown_note(recs: list[Session], pricing: dict):
    un = stats.unknown_models(recs, pricing)
    if un:
        console().print(f"[yellow]注: 成本带 * 的模型无定价，token 已统计、成本按 $0 计：{', '.join(un)}[/yellow]")


def _make_table(title_rule: str, title: str | None = None) -> Table:
    return Table(title=title, box=box.SIMPLE_HEAVY if title_rule == "=" else box.SIMPLE,
                 header_style="bold", show_header=True)


def view_flat(recs: list[Session], pricing: dict):
    """实体（会话/文件）明细。"""
    tb = _make_table("-")
    for col, kw in [("时间", {}), ("ID", {}), ("类型", {}), ("代理/父线程", {"overflow": "ellipsis"}),
                    ("模型", {})]:
        tb.add_column(col, **kw)
    _add_metric_columns(tb)
    acc = _acc()
    for r in sorted(recs, key=stats.sort_key):
        d, t = stats.fmt_dt(r)
        gin, ca, out = stats.rec_tokens(r)
        cost, known = stats.rec_cost(r, pricing)
        calls = stats.rec_calls(r)
        mm = r.primary_model + ("+mix" if r.multi_model else "")
        _metric_row(tb, [f"{d[5:]} {t}", r.sid[:13], _type_cell(r.type), _note(r),
                         _model_cell(mm)],
                    [gin - ca, ca, out, calls, cost, known])
        _merge_acc(acc, gin - ca, ca, out, calls, cost, known)
    _metric_row(tb, [Text(f"合计 {len(recs)} 会话", style="bold"), "", "", "", ""], acc, style="bold")
    console().print(tb)
    print_unknown_note(recs, pricing)


def view_models(recs: list[Session], pricing: dict):
    """--by-model 聚合：每个模型一行。"""
    agg = stats.aggregate_models(recs, pricing)
    tb = _make_table("=")
    tb.add_column("模型")
    tb.add_column("会话数", justify="right")
    _add_metric_columns(tb)
    tot = _acc()
    for mname, a in sorted(agg.items(), key=lambda kv: -(kv[1][0] + kv[1][1])):
        _metric_row(tb, [_model_cell(mname), f"{a[6]}"], a[:6])
        _merge_acc(tot, *a[:6])
    _metric_row(tb, [Text(f"合计 {len(recs)} 会话", style="bold"), ""], tot, style="bold")
    console().print(tb)
    print_unknown_note(recs, pricing)


def view_by_day(recs: list[Session], pricing: dict, by_model: bool):
    """--by-day 聚合：天一行；--by-model 组合时 天×模型。"""
    tb = _make_table("=")
    tb.add_column("日期")
    if by_model:
        tb.add_column("模型")
        tb.add_column("会话数", justify="right")
    _add_metric_columns(tb)
    grand = _acc()
    if by_model:
        by_day: dict[str, list[Session]] = {}
        for r in recs:
            by_day.setdefault(stats.fmt_dt(r)[0], []).append(r)
        for d in sorted(by_day):
            agg = stats.aggregate_models(by_day[d], pricing)
            dtot = _acc()
            for mname, a in sorted(agg.items(), key=lambda kv: -(kv[1][0] + kv[1][1])):
                _metric_row(tb, [d, _model_cell(mname), f"{a[6]}"], a[:6])
                _merge_acc(dtot, *a[:6])
            tb.add_section()
            _metric_row(tb, [Text("小计", style="dim"), Text("当日合计", style="dim"), ""],
                        dtot, style="dim")
            _merge_acc(grand, *dtot)
    else:
        day_agg: dict[str, list] = {}
        for r in recs:
            d, _ = stats.fmt_dt(r)
            gin, ca, out = stats.rec_tokens(r)
            cost, known = stats.rec_cost(r, pricing)
            _merge_acc(day_agg.setdefault(d, _acc()),
                       gin - ca, ca, out, stats.rec_calls(r), cost, known)
        for d in sorted(day_agg):
            _metric_row(tb, [d], day_agg[d])
            _merge_acc(grand, *day_agg[d])
    label = Text(f"合计 {len(recs)} 会话", style="bold")
    _metric_row(tb, [label, "", ""] if by_model else [label], grand, style="bold")
    console().print(tb)
    print_unknown_note(recs, pricing)


def view_families(recs: list[Session], pricing: dict, by_model: bool, by_day: bool):
    """--family：家族树明细；--by-model 时 家族×模型聚合；--by-day 时按天分组。"""

    def emit_group(sub: list[Session], tb: Table):
        by_sid = {r.sid: r for r in sub}
        families: dict[str, list[Session]] = {}
        roots: list[Session] = []
        for r in sub:
            if r.type == "subagent" and r.parent:
                parent = next((s for s in by_sid if s.startswith(r.parent)), r.parent)
                if parent in by_sid:
                    families.setdefault(parent, []).append(r)
                else:
                    families.setdefault(r.parent, []).append(r)
            else:
                roots.append(r)

        gacc = _acc()

        def label_row(note: str, r: Session | None, blank_id: bool = False):
            d, t = stats.fmt_dt(r) if r else ("", "")
            tb.add_row(f"{d[5:]} {t}" if r else "",
                       (r.parent or "?")[:13] if blank_id else (r.sid[:13] if r else ""),
                       _type_cell(r.type if r else None), Text(note, style="bold"))

        def model_agg_rows(members: list[Session]) -> list:
            agg = stats.aggregate_models(members, pricing)
            acc = _acc()
            for mname, a in sorted(agg.items(), key=lambda kv: -(kv[1][0] + kv[1][1])):
                _metric_row(tb, ["", "", "", "", _model_cell(mname)], a[:6])
                _merge_acc(acc, *a[:6])
            return acc

        def render_family(root: Session, children: list[Session], note_override: str | None = None):
            members = [root] + children
            if note_override:
                label_row(note_override, root, blank_id=True)
            elif by_model:
                d, t = stats.fmt_dt(root)
                tb.add_row(f"{d[5:]} {t}", root.sid[:13], _type_cell(root.type),
                           Text(f"{len(members)} 会话", style="bold"))
            if by_model:
                acc = model_agg_rows(members)
            else:
                acc = _acc()
                rows = [(root, "")]
                rows += [(ch, "└ " + (ch.agent or "subagent")) for ch in
                         sorted(children, key=stats.sort_key)]
                for m, note in rows:
                    d, t = stats.fmt_dt(m)
                    gin, ca, out = stats.rec_tokens(m)
                    cost, known = stats.rec_cost(m, pricing)
                    mm = m.primary_model + ("+mix" if m.multi_model else "")
                    _metric_row(tb, [f"{d[5:]} {t}", m.sid[:13], _type_cell(m.type),
                                     Text(note, style="cyan") if note else Text(_note(m)),
                                     _model_cell(mm)],
                                [gin - ca, ca, out, stats.rec_calls(m), cost, known])
                    _merge_acc(acc, gin - ca, ca, out, stats.rec_calls(m), cost, known)
            if len(members) > 1:
                tb.add_section()
                _metric_row(tb, [Text("家族小计", style="dim"), "", "", "", ""], acc, style="dim")
            _merge_acc(gacc, *acc)

        for root in sorted(roots, key=stats.sort_key):
            children = sorted(families.get(root.sid, []), key=stats.sort_key)
            render_family(root, children)
        for pid, children in sorted(families.items()):
            if pid in by_sid:
                continue
            children = sorted(children, key=stats.sort_key)
            render_family(children[0], children[1:], note_override=f"(父不在范围内) {len(children)} 会话")
        return gacc

    tb = _make_table("=")
    for col, kw in [("时间", {}), ("ID", {}), ("类型", {}), ("代理/父线程", {"overflow": "ellipsis"}),
                    ("模型", {})]:
        tb.add_column(col, **kw)
    _add_metric_columns(tb)

    grand = _acc()
    if by_day:
        from collections import defaultdict
        groups: dict[str, list[Session]] = defaultdict(list)
        for r in recs:
            groups[stats.fmt_dt(r)[0]].append(r)
        for day in sorted(groups):
            tb.add_section()
            tb.add_row(Text(f"──────── {day} ────────", style="bold"), "", "", "", "", "", "", "")
            acc = emit_group(groups[day], tb)
            tb.add_section()
            _metric_row(tb, [Text(f"小计 {day}", style="bold"), "", "", "", ""], acc, style="bold")
            _merge_acc(grand, *acc)
        _metric_row(tb, [Text("总计", style="bold"), "", "", "", ""], grand, style="bold")
    else:
        grand = emit_group(recs, tb)
        _metric_row(tb, [Text(f"合计 {len(recs)} 会话", style="bold"), "", "", "", ""], grand, style="bold")
    console().print(tb)
    print_unknown_note(recs, pricing)
