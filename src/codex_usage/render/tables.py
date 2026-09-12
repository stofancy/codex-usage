"""终端表格视图（rich 实现：CJK 宽字符精确对齐、颜色、无 TTY 自动去色）。"""

import sys

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from ..parser import Session
from .. import stats

TYPE_STYLE = {"user": "", "subagent": "cyan", "guardian": "yellow",
              "voice": "magenta", "handoff": "blue", "agent": "green"}

METRIC_LABEL = {"cost": "成本", "input": "净输入", "cache": "缓存读",
                "output": "输出", "total": "总 tokens"}


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


def _add_total(tb: Table, label: str, net: int, cached: int, out: int, cost: float, known: bool):
    cost_s = f"${cost:,.2f}" + ("" if known else "*")
    tb.add_section()
    tb.add_row(Text(label, style="bold"), "", "", "",
               Text(f"{net:,}", style="bold"), Text(f"{cached:,}", style="bold"),
               Text(f"{out:,}", style="bold"), Text(cost_s, style="bold"))


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
                    ("模型", {}), ("净输入", {"justify": "right"}), ("缓存读", {"justify": "right"}),
                    ("输出", {"justify": "right"}), ("成本", {"justify": "right"})]:
        tb.add_column(col, **kw)
    acc = [0, 0, 0, 0.0, True]
    for r in sorted(recs, key=stats.sort_key):
        d, t = stats.fmt_dt(r)
        gin, ca, out = stats.rec_tokens(r)
        cost, known = stats.rec_cost(r, pricing)
        mm = r.primary_model + ("+mix" if r.multi_model else "")
        tb.add_row(f"{d[5:]} {t}", r.sid[:13], _type_cell(r.type), _note(r),
                   _model_cell(mm), f"{gin-ca:,}", f"{ca:,}", f"{out:,}",
                   f"${cost:,.2f}" + ("" if known else "*"))
        acc[0] += gin - ca; acc[1] += ca; acc[2] += out; acc[3] += cost
        acc[4] = acc[4] and known
    _add_total(tb, f"合计 {len(recs)} 会话", *acc)
    console().print(tb)
    print_unknown_note(recs, pricing)


def view_models(recs: list[Session], pricing: dict):
    """--by-model 聚合：每个模型一行。"""
    agg = stats.aggregate_models(recs, pricing)
    tb = _make_table("=")
    for col, kw in [("模型", {}), ("会话数", {"justify": "right"}), ("净输入", {"justify": "right"}),
                    ("缓存读", {"justify": "right"}), ("输出", {"justify": "right"}),
                    ("成本", {"justify": "right"})]:
        tb.add_column(col, **kw)
    tot = [0, 0, 0, 0.0, True]
    for mname, a in sorted(agg.items(), key=lambda kv: -(kv[1][0] + kv[1][1])):
        tb.add_row(_model_cell(mname), f"{a[5]}", f"{a[0]:,}", f"{a[1]:,}",
                   f"{a[2]:,}", f"${a[3]:,.2f}" + ("" if a[4] else "*"))
        for i in range(5):
            tot[i] += a[i]
    _add_total(tb, f"合计 {len(recs)} 会话", *tot)
    console().print(tb)
    print_unknown_note(recs, pricing)


def view_by_day(recs: list[Session], pricing: dict, by_model: bool):
    """--by-day 聚合：天一行；--by-model 组合时 天×模型。"""
    tb = _make_table("=")
    cols = [("日期", {})]
    if by_model:
        cols += [("模型", {}), ("会话数", {"justify": "right"})]
    cols += [("净输入", {"justify": "right"}), ("缓存读", {"justify": "right"}),
             ("输出", {"justify": "right"}), ("成本", {"justify": "right"})]
    for col, kw in cols:
        tb.add_column(col, **kw)
    grand = [0, 0, 0, 0.0, True]
    if by_model:
        day_agg: dict[str, dict[str, list]] = {}
        for r in recs:
            d, _ = stats.fmt_dt(r)
            da = day_agg.setdefault(d, {})
            seen = set()
            for mname, v in r.models.items():
                from ..pricing import model_cost
                c = model_cost(pricing, mname, v[0] - v[1], v[1], v[2])
                a = da.setdefault(mname, [0, 0, 0, 0.0, True, 0])
                a[0] += v[0] - v[1]; a[1] += v[1]; a[2] += v[2]
                a[3] += c or 0.0
                a[4] = a[4] and (c is not None)
                if mname not in seen:
                    a[5] += 1
                    seen.add(mname)
        for d in sorted(day_agg):
            dtot = [0, 0, 0, 0.0, True]
            for mname, a in sorted(day_agg[d].items(), key=lambda kv: -(kv[1][0] + kv[1][1])):
                tb.add_row(d, _model_cell(mname), f"{a[5]}", f"{a[0]:,}", f"{a[1]:,}",
                           f"{a[2]:,}", f"${a[3]:,.2f}" + ("" if a[4] else "*"))
                for i in range(5):
                    dtot[i] += a[i]
            tb.add_section()
            tb.add_row(Text("小计", style="dim"), Text("当日合计", style="dim"), "",
                       Text(f"{dtot[0]:,}", style="dim"), Text(f"{dtot[1]:,}", style="dim"),
                       Text(f"{dtot[2]:,}", style="dim"),
                       Text(f"${dtot[3]:,.2f}" + ("" if dtot[4] else "*"), style="dim"))
            for i in range(5):
                grand[i] += dtot[i]
    else:
        day_agg: dict[str, list] = {}
        for r in recs:
            d, _ = stats.fmt_dt(r)
            gin, ca, out = stats.rec_tokens(r)
            cost, known = stats.rec_cost(r, pricing)
            a = day_agg.setdefault(d, [0, 0, 0, 0.0, True])
            a[0] += gin - ca; a[1] += ca; a[2] += out
            a[3] += cost; a[4] = a[4] and known
        for d in sorted(day_agg):
            a = day_agg[d]
            tb.add_row(d, f"{a[0]:,}", f"{a[1]:,}", f"{a[2]:,}",
                       f"${a[3]:,.2f}" + ("" if a[4] else "*"))
            for i in range(5):
                grand[i] += a[i]
    _add_total(tb, f"合计 {len(recs)} 会话", *grand)
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

        gacc = [0, 0, 0, 0.0, True]

        def label_row(note: str, r: Session | None, blank_id: bool = False):
            d, t = stats.fmt_dt(r) if r else ("", "")
            tb.add_row(f"{d[5:]} {t}" if r else "",
                       (r.parent or "?")[:13] if blank_id else (r.sid[:13] if r else ""),
                       _type_cell(r.type if r else None), Text(note, style="bold"))

        def model_agg_rows(members: list[Session]) -> list:
            agg = stats.aggregate_models(members, pricing)
            acc = [0, 0, 0, 0.0, True]
            for mname, a in sorted(agg.items(), key=lambda kv: -(kv[1][0] + kv[1][1])):
                tb.add_row("", "", "", "", _model_cell(mname), f"{a[0]:,}", f"{a[1]:,}",
                           f"{a[2]:,}", f"${a[3]:,.2f}" + ("" if a[4] else "*"))
                for i in range(5):
                    acc[i] += a[i]
            return acc

        def render_family(root: Session, children: list[Session], note_override: str | None = None):
            members = [root] + children
            if by_model:
                if note_override:
                    label_row(note_override, root, blank_id=True)
                else:
                    d, t = stats.fmt_dt(root)
                    tb.add_row(f"{d[5:]} {t}", root.sid[:13], _type_cell(root.type),
                               Text(f"{len(members)} 会话", style="bold"))
                acc = model_agg_rows(members)
            else:
                if note_override:
                    label_row(note_override, root, blank_id=True)
                acc = [0, 0, 0, 0.0, True]
                rows = [(root, "")]
                rows += [(ch, "└ " + (ch.agent or "subagent")) for ch in
                         sorted(children, key=stats.sort_key)]
                for m, note in rows:
                    d, t = stats.fmt_dt(m)
                    gin, ca, out = stats.rec_tokens(m)
                    cost, known = stats.rec_cost(m, pricing)
                    mm = m.primary_model + ("+mix" if m.multi_model else "")
                    tb.add_row(f"{d[5:]} {t}", m.sid[:13], _type_cell(m.type),
                               Text(note, style="cyan") if note else Text(_note(m)),
                               _model_cell(mm), f"{gin-ca:,}", f"{ca:,}", f"{out:,}",
                               f"${cost:,.2f}" + ("" if known else "*"))
                    acc[0] += gin - ca; acc[1] += ca; acc[2] += out; acc[3] += cost
                    acc[4] = acc[4] and known
            if len(members) > 1:
                tb.add_section()
                tb.add_row(Text("家族小计", style="dim"), "", "", "",
                           Text(f"{acc[0]:,}", style="dim"), Text(f"{acc[1]:,}", style="dim"),
                           Text(f"{acc[2]:,}", style="dim"),
                           Text(f"${acc[3]:,.2f}" + ("" if acc[4] else "*"), style="dim"))
            for i in range(5):
                gacc[i] += acc[i]

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
                    ("模型", {}), ("净输入", {"justify": "right"}), ("缓存读", {"justify": "right"}),
                    ("输出", {"justify": "right"}), ("成本", {"justify": "right"})]:
        tb.add_column(col, **kw)

    grand = [0, 0, 0, 0.0, True]
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
            tb.add_row(Text(f"小计 {day}", style="bold"), "", "", "",
                       Text(f"{acc[0]:,}", style="bold"), Text(f"{acc[1]:,}", style="bold"),
                       Text(f"{acc[2]:,}", style="bold"),
                       Text(f"${acc[3]:,.2f}" + ("" if acc[4] else "*"), style="bold"))
            for i in range(5):
                grand[i] += acc[i]
        _add_total(tb, "总计", *grand)
    else:
        grand = emit_group(recs, tb)
        _add_total(tb, f"合计 {len(recs)} 会话", *grand)
    console().print(tb)
    print_unknown_note(recs, pricing)
