# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Versioning notes

- The first public release is `0.1.0` (2026-09-21); the project deliberately stays in the
  `0.x` range so that breaking changes are still allowed before `1.0.0`.
- Unreleased work goes under `[Unreleased]`; at release time that section is renamed to
  `[X.Y.Z] - YYYY-MM-DD` and a fresh empty `[Unreleased]` opens.
- The `--json` and `--schema` output shapes are part of the public contract: breaking
  changes there bump MAJOR (while in `0.x`, at least MINOR with a migration note).
- Entries use the Keep a Changelog categories: Added, Changed, Deprecated, Removed,
  Fixed, Security.

## [Unreleased]

## [0.3.0] - 2026-09-21

### Added

- Cache hit rate: every table gained a hit-rate column and charts accept `--metric hit`. The
  ratio is cache read ÷ gross input (gross input includes cache read), the same definition as
  the API's `cached_tokens / input_tokens`. Aggregates are weighted (Σ cache read ÷ Σ gross
  input) so grouping by day, model or family never degenerates into an average of per-row
  percentages; rows with no input show `-` instead of a misleading 0%. `--json` exposes
  `cache_hit_rate` per session and per model (null when there is no input). `--chart pie`
  rejects the metric because share-of-total is meaningless for a ratio.

## [0.2.1] - 2026-09-21

### Fixed

- `--session <uuid>` now matches any UUID in the rollout file name, so `--raw` picks up
  paginated continuation files (the continuation page's session id is the trailing UUID).
  Paginated sessions account for 7.88% of the window's tokens on the maintainer's data;
  the default (merged) view was always correct.

## [0.2.0] - 2026-09-21

### Changed

- `--json` gained `metering` (`resets` / `fallbacks` / `delta_sum`) and `tiers` (per model ×
  service tier, from `thread_settings_applied`) so metering decisions are auditable; `--schema`
  documents both. `--doctor` additionally reports how much of the pricing table lacks a
  cache-read price.
- Cost estimation is now service-tier aware: `priority` and `fast` are one tier (the official
  rename of priority processing) and are priced with the official per-model Fast rates — 2.0×
  standard for Astra and the 5.6 Sol/Terra/Luna family, 2.5× for `gpt-5.5`, while `flex` is
  0.5×. The rates come from `data/tier_pricing.json` (override with
  `CODEX_USAGE_TIER_PRICING_FILE`) and are declared as API-equivalent USD, not the ChatGPT
  subscription credit multipliers. Models without a public Fast price stay at the standard
  price and report `tier_priced: false`.
- Labels that no public source prices now go through an auditable alias table
  (`data/model_aliases.json`, override with `CODEX_USAGE_ALIASES_FILE`): `codex-auto-review`
  is priced as `gpt-5.5` and flagged `assumed: true`, while `gpt-reserve` is deliberately left
  unpriced (`$0.00*`) instead of being guessed.

### Fixed

- Token metering now follows the cumulative `total_token_usage` delta instead of summing the
  per-turn `last_token_usage`: 53% of session files repeat a cumulative snapshot, and some
  subagent files start with an inherited parent-history snapshot (the largest at 14,051,760
  tokens with a zero delta), so the old path over-counted and double-counted replayed
  prefixes. The first snapshot is counted at its own delta, a mid-file jump larger than that
  turn's delta is capped by it, and a cumulative drop (context compaction) or a missing
  cumulative field falls back to `last_token_usage`.
- Cross-day long sessions: file admission now also includes rollout files whose path date is
  outside the window but whose mtime is at or after `--since`. Previously those turns were
  dropped — 62,780,912 tokens and $66.75 in the fixed verification window
  (`--since 20260911 --until 20260912`). With the fix the per-(day, model) token ledger
  matches ccusage exactly (both 1,830,205,933 tokens, difference 0).
- Pagination merge: a merged session now accumulates `tiers` alongside `models`, so the tier
  totals agree with the model totals again (the previous mismatch was 4.81M gross input
  tokens).
- `sessions/` and `archived_sessions/` copies of the same session are now de-duplicated
  (`sessions/` wins) instead of being summed into one session.
- Pricing: a missing or explicitly zero `cacheReadCostPerMillion` now falls back to that
  model's input price instead of charging cached reads at $0 (33.6% of the effective table has
  no cache-read price).

### Documentation

- Both READMEs document the cumulative-delta metering rules (including the cross-day file
  admission), the cache-read / service-tier / alias pricing behaviour, and the fixed-window
  reconciliation with ccusage (identical tokens, +$51.40 cost because ccusage does not apply
  the `gpt-6-astra` Fast rate).

## [0.1.0] - 2026-09-21

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
