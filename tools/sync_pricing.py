#!/usr/bin/env python3
"""生成 / 更新内置定价表 src/codex_usage/data/pricing.json（构建期工具，需网络）。

公开渠道（免认证）：
    models.dev  https://models.dev/api.json                          cost 单位 $/M tokens
    litellm     BerriAI/litellm model_prices_and_context_window.json *_cost_per_token 单位 $/token

输出为 cc-switch 兼容格式，供 src/codex_usage/pricing.py 直接读取：
    {"source": ..., "updated": ..., "models": [{"modelId", "inputCostPerMillion",
      "cacheReadCostPerMillion", "outputCostPerMillion"}, ...]}

用法::

    # 真实拉取 models.dev 并刷新内置表（默认输出）
    python tools/sync_pricing.py

    # 备选渠道 / 指定输出 / 离线用本地快照重建
    python tools/sync_pricing.py --source litellm --out /tmp/pricing.json
    python tools/sync_pricing.py --source models.dev --input .scratch/models.dev.json

    # 只统计不落盘；或保留渠道原始 JSON 供对比
    python tools/sync_pricing.py --dry-run
    python tools/sync_pricing.py --format raw --out /tmp/models.dev.json
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:       # 源码树优先，避免用到过期的安装版本
    sys.path.insert(0, str(ROOT / "src"))

from codex_usage import pricing              # noqa: E402

DEFAULT_OUT = ROOT / "src" / "codex_usage" / "data" / "pricing.json"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="sync_pricing.py",
        description="生成/更新 codex-usage 内置定价表（cc-switch 兼容格式）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("用法::")[-1].strip(),
    )
    ap.add_argument("--source", choices=sorted(pricing.SOURCES), default=pricing.DEFAULT_SOURCE,
                    help="定价渠道（默认 %(default)s）")
    ap.add_argument("--out", default=str(DEFAULT_OUT),
                    help="输出路径（默认内置表 %(default)s）")
    ap.add_argument("--format", choices=("cc-switch", "raw"), default="cc-switch",
                    help="cc-switch=归一化定价表（默认）；raw=渠道原始 JSON")
    ap.add_argument("--input", help="离线输入：本地渠道 JSON（给定时不联网）")
    ap.add_argument("--timeout", type=float, default=60.0, help="下载超时秒数（默认 %(default)s）")
    ap.add_argument("--updated", help="覆盖 updated 时间戳（ISO8601，便于可复现生成）")
    ap.add_argument("--dry-run", action="store_true", help="只统计与校验，不写文件")
    return ap


def _size_mb(n: int) -> str:
    return f"{n / 1024 / 1024:.2f} MB"


def _dump(path: Path, payload) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return len(text.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    origin = args.input or pricing.SOURCES[args.source]["url"]
    t0 = time.monotonic()
    try:
        if args.input:
            raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
        else:
            raw = pricing.fetch_source(args.source, args.timeout)
    except Exception as exc:
        print(f"错误: 读取定价渠道失败（{origin}）: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    elapsed = time.monotonic() - t0

    if args.format == "raw":
        if args.dry_run:
            print(f"渠道 {args.source} 原始 JSON：{len(json.dumps(raw))} 字节，耗时 {elapsed:.2f}s")
            return 0
        out = Path(args.out)
        written = _dump(out, raw)
        print(f"渠道 {args.source} 原始 JSON → {out}（{_size_mb(written)}，耗时 {elapsed:.2f}s）")
        return 0

    records = pricing.records_from(args.source, raw)
    unit = "个 provider" if args.source == "models.dev" else "个顶层条目"
    print(f"渠道      {args.source}（{'本地 ' + args.input if args.input else pricing.SOURCES[args.source]['url']}）")
    print(f"读取      {_size_mb(len(json.dumps(raw)))}，耗时 {elapsed:.2f}s")
    print(f"解析      {len(raw) if isinstance(raw, dict) else 0} {unit}，去重后有价模型 {len(records)} 个")
    if not records:
        print("错误: 未解析出任何可用定价，已中止", file=sys.stderr)
        return 1

    if args.dry_run:
        print("dry-run   未写文件")
        return 0

    out = Path(args.out)
    updated = args.updated or datetime.now(timezone.utc).isoformat(timespec="seconds")
    pricing.write_pricing_table(str(out), records, source=args.source, updated=updated)
    written = len(out.read_text(encoding="utf-8").encode("utf-8"))
    try:
        shown = out.relative_to(ROOT)
    except ValueError:
        shown = out
    print(f"写入      {shown}（{_size_mb(written)}，updated={updated}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
