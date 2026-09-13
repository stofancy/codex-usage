# Security Policy

## Supported versions

| Version | Security fixes |
|---|---|
| 0.1.x | yes |
| anything older | no releases exist yet |

## What this tool touches (privacy facts)

codex-usage is a local, read-only analytics tool. These are the exact behaviours that
matter for security review:

| Aspect | Behaviour |
|---|---|
| Data read | Local Codex rollout session files (default `~/.codex/sessions` and `~/.codex/archived_sessions`) and a pricing table (default `~/.cc-switch/model-pricing.json`) |
| Path overrides | `CODEX_USAGE_SESSIONS_DIR`, `CODEX_USAGE_ARCHIVE_DIR`, `CODEX_USAGE_PRICING_FILE`, `CODEX_USAGE_CACHE_DIR` |
| Network by default | **None.** Parsing, aggregation, tables, ASCII charts and real-image rendering all happen locally |
| Writes by default | **None.** Session files are never modified, moved or deleted |
| Pricing cache | Only `--update-pricing` writes a file, and only to `~/.cache/codex-usage/pricing.json` (atomic write; `CODEX_USAGE_CACHE_DIR` overrides the directory) |
| Charts | Rendered in memory (including the matplotlib PNG for real-image mode) and sent straight to the terminal - **never written to disk** |
| Telemetry | None. No analytics, no crash reporting, no phone-home |
| Output | Data goes to stdout; diagnostics and errors go to stderr |
| Pricing table resolution | `CODEX_USAGE_PRICING_FILE` -> user cache -> a pricing table bundled with the package (`src/codex_usage/data/pricing.json`), so the tool works fully offline out of the box |

### The only network path: `--update-pricing`

`codex-usage --update-pricing` is optional, and its boundaries are:

- It runs **only** when the user explicitly passes the flag; nothing else in the tool
  opens a socket, and no implicit refresh happens in the background.
- `--pricing-source models.dev` (default) downloads <https://models.dev/api.json>;
  `--pricing-source litellm` downloads the LiteLLM price table from
  `https://raw.githubusercontent.com/BerriAI/litellm/main/...`. Both are public,
  unauthenticated price datasets; the requests are plain HTTPS with a 30 s timeout.
- It **does not** upload or transmit any local data: not session contents, not token
  statistics, not file paths, not environment information.
- The result is a local pricing file. Nothing about your usage leaves the machine.

## Reporting a vulnerability

Please use GitHub's private channel:

1. Open the repository's **Security** tab -> **Report a vulnerability**
   (<https://github.com/stofancy/codex-usage/security/advisories/new>), or
2. Contact the maintainer [@stofancy](https://github.com/stofancy) privately on GitHub.

Do not open a public issue for a security problem, and avoid posting exploit details in
public discussions.

Please include: affected version, reproduction steps or a minimal sample, the impact you
believe it has (information disclosure, arbitrary file read/write, code execution, ...)
and how to reach you. We will acknowledge the report as soon as possible, fix it in a new
release, and credit you in the Security section of [CHANGELOG.md](CHANGELOG.md) unless you
prefer to stay anonymous.

## Out of scope

- Vulnerabilities in third-party dependencies (rich, plotext, termcharts, matplotlib,
  textual-image). Report those upstream; we are happy to pick up upgraded versions.
- Attacks that require the local session files to be malicious: they are treated as trusted
  user data. We do, however, welcome reports about **parser robustness** (malformed input
  causing crashes or unbounded resource use).
- Scenarios that require the user to point a `CODEX_USAGE_*` variable at a hostile path.
