# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Versioning notes

- **Nothing has been released yet.** The first public release will be `0.1.0`
  (the `version` field in `pyproject.toml`); the project deliberately stays in the `0.x`
  range so that breaking changes are still allowed before `1.0.0`.
- Everything below is therefore collected under `[Unreleased]`. At release time that
  section is renamed to `[0.1.0] - YYYY-MM-DD` and a fresh empty `[Unreleased]` opens.
- The `--json` and `--schema` output shapes are part of the public contract: breaking
  changes there bump MAJOR (while in `0.x`, at least MINOR with a migration note).
- Entries use the Keep a Changelog categories: Added, Changed, Deprecated, Removed,
  Fixed, Security.

## [Unreleased]

### Added

- **CLI** `codex-usage`: parses local Codex rollout session files and aggregates token
  usage by session / subagent / day / model, rendered as rich terminal tables and charts.
- **More accurate metering**: per-turn `last_token_usage` deltas instead of the
  `total_token_usage` counters, which context compaction can leave far below the real totals.
- **Flexible aggregation**: combinable `--by-day` / `--by-model` (including day x model),
  family-tree and per-file views, and filters for time range, entry type, model, session,
  parent and archived sessions. `--since` / `--until` accept both explicit and compact
  (`20260912-1610`) time formats.
- **Cost estimation**: per-model cost from a pricing table, with a built-in offline table
  shipped in the package (`src/codex_usage/data/pricing.json`). Unknown models are still
  counted, priced at $0 and flagged in the output.
- **Charts**: `--chart pie|bar|area|line` with `--metric cost|input|cache|output|total`.
  - Real-image rendering (`matplotlib` -> PNG -> terminal) in terminals that support a
    graphics protocol (kitty TGP / Sixel), with a colored half-cell fallback elsewhere.
    Requires the optional `[image]` extra; `textual-image` requires Python >= 3.12.
  - ASCII charts (plotext + termcharts) when `[image]` is not installed, output is
    redirected, or `--ascii` is passed.
- **Chart rendering mode override**: the `CODEX_USAGE_IMAGE_MODE` environment variable
  (`auto` (default) | `tgp` | `sixel` | `halfcell` | `ascii`), for terminals whose
  auto-detection misbehaves. Invalid values fall back to `auto`.
- **Table metric columns**: API `calls` and `cost per call`.
- **Self-description and self-check**: expanded `--help` (also `/?`, `-?`, `help`) covering
  examples, semantics, exit codes and data sources; a machine-readable `--schema` contract
  generated from the argparse definition; and `--doctor` for environment diagnostics
  (data sources, pricing, real-image capability, terminal mode, CJK fonts), with `--json`
  for structured output.
- **Optional pricing refresh**: `--update-pricing` (source selectable via
  `--pricing-source models.dev|litellm`) downloads a public pricing table and writes it to
  the user cache (`~/.cache/codex-usage/pricing.json`, override with `CODEX_USAGE_CACHE_DIR`).
  This is the only code path that uses the network, and it never runs implicitly.
- **Machine-readable output**: `--json` emits per-session records including per-model
  details. Data is written to stdout only; diagnostics and errors go to stderr.
- **Environment overrides**: `CODEX_USAGE_SESSIONS_DIR`, `CODEX_USAGE_ARCHIVE_DIR`,
  `CODEX_USAGE_PRICING_FILE`, `CODEX_USAGE_CACHE_DIR`, `CODEX_USAGE_IMAGE_MODE`.
- **Typing**: a `py.typed` marker so downstream type checkers use the bundled annotations.
- **Engineering and community baseline**: GitHub Actions CI (Python 3.10-3.13 matrix plus a
  ruff/mypy job), `ruff.toml`, `mypy.ini`, this changelog, CONTRIBUTING, SECURITY,
  CODE_OF_CONDUCT, GitHub issue forms, a pull request template and `.editorconfig`.

### Changed

- ASCII chart titles and legends are transliterated to ASCII: plotext lays out one column
  per character, so wide CJK characters used to misalign into garbage. Real-image and
  half-cell modes keep CJK labels.
- Chart raster size now follows the terminal's reported pixel size (avoids upscaling the
  PNG and blurring thin lines), crowded x-axis labels are thinned out, and axis ticks use
  compact forms such as `120K` / `3.4B`.

### Fixed

- Test fixtures no longer hard-code UTC timestamps: they follow the host time zone, so the
  suite passes on runners in any zone (it failed on every CI Python version before).
- Real-image charts: rotated x-axis labels no longer push into the plot area, and legends
  plus edge margins now keep all content inside the canvas on narrow rasters and on hosts
  without a CJK font (both surfaced by the first CI run and covered by
  `test_charts_survive_without_cjk_font`).

### Documentation

- README reworked for the public release (English primary, Chinese translation alongside):
  installation, usage, time-format and table-column semantics, chart rendering modes and
  terminal examples.
