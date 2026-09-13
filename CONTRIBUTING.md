# Contributing

Thanks for taking the time to improve codex-usage. This document explains how to set up
the project, run the tests and get a change merged.

By participating you agree to follow our [Code of Conduct](CODE_OF_CONDUCT.md).

## Requirements

- Python >= 3.10 (CI covers 3.10, 3.11, 3.12 and 3.13)
- git
- Optional, for real-image chart development: a terminal that supports a graphics protocol
  (kitty, Ghostty, WezTerm, Konsole, foot, xterm-sixel, ...) plus the `[image]` extra

## Local setup

```bash
git clone https://github.com/stofancy/codex-usage
cd codex-usage

python3 -m venv .venv
.venv/bin/python -m pip install -e ".[image]" pytest   # drop [image] if you don't need charts
```

## Running the tests

```bash
.venv/bin/python -m pytest tests/ -q
```

- The test suite uses synthetic fixtures: it does not read your `~/.codex` directory and
  does not touch the network.
- When only the base dependencies are installed (`-e .` instead of `-e ".[image]"`), the
  real-image tests are skipped automatically. That is expected, not a failure.
- Please make sure the suite is green before opening a pull request (the suite currently
  has around 99 tests; the exact count varies with the Python version and with whether
  `[image]` is installed).

## Static checks

```bash
ruff check .        # configuration: ruff.toml
mypy src            # configuration: mypy.ini
```

If the tools are missing locally: `python -m pip install ruff mypy`. CI installs them in
the `lint` job.

### Quality gates and the known baseline

| Check | Configuration | Current state |
|---|---|---|
| `pytest -q` | `[tool.pytest.ini_options]` in `pyproject.toml` | green, blocks CI |
| `ruff check .` | `ruff.toml` (`E4`, `E7`, `E9`, `F`) | ~13 pre-existing findings, see below |
| `mypy src` | `mypy.ini` (non-strict, `ignore_missing_imports`) | baseline count unknown until the first CI run |

Known ruff baseline (collected by static inspection; the exact list may shift by an item
or two on the first real `ruff` run):

| Location | Rule | Note |
|---|---|---|
| `src/codex_usage/parser.py:169` | E741 | variable named `l`, easily confused with `1` |
| `src/codex_usage/pricing.py:273` | E731 | `f = lambda ...`, prefer `def` |
| `tests/test_imgcharts.py:5` | F401 | unused `import warnings` |
| `tests/test_cli_e2e.py:50,51,59,73,115,116,117` | E741 | variables named `l` |
| `tests/test_selfdoc.py:47` | E741 | variable named `l` |
| `tools/make_doc_shots.py:439,440` | E731 | lambda assignments |

Rule of thumb: **new code must not add to the baseline.** Until the existing findings are
cleared, the CI `lint` job is marked `continue-on-error: true` (report only, no PR block);
once the baseline is clean, remove that line in `.github/workflows/ci.yml` to turn it into
a real gate.

The `I` (isort) ruleset is not enabled yet: enabling it would immediately surface
import-ordering findings in a few files (`src/codex_usage/parser.py`,
`src/codex_usage/render/tables.py`, `tests/test_stats.py`, `tools/make_doc_shots.py`).
Once those imports are sorted, add `"I"` to `select` in `ruff.toml`.

## Code and commit conventions

- Commit messages follow the existing style `<area>: <summary>`; keep one change per commit.
- Style: 4-space indentation, lines <= 100 columns, UTF-8, LF (see `.editorconfig`).
  No formatter is enforced - please do not reformat the whole codebase in a feature PR.
- Typing: annotate new functions in `src/` where practical. Type checking is currently
  non-strict.
- Dependencies: open an issue before adding a runtime dependency, and keep `[image]`
  optional. `plotext` is intentionally pinned.
- Behaviour boundaries that every pull request must preserve (see
  [SECURITY.md](SECURITY.md) for the full statement):
  - **No network access by default.** The only network path is `--update-pricing`, which
    runs only when the user asks for it.
  - Never write to, modify or delete the user's session or pricing files. The only file
    this tool creates is the optional pricing cache in `~/.cache/codex-usage/`.
  - Charts are rendered in memory and sent straight to the terminal - never written to disk.
  - Data goes to stdout only; diagnostics and errors go to stderr.
  - `--json` and `--schema` are public contracts; note compatibility impact for changes.

## Pull request process

1. Fork the repository and create a branch (for example `fix/until-boundary`).
2. Add or update tests, and record the change under `[Unreleased]` in `CHANGELOG.md`.
3. Run `pytest` locally (plus `ruff` / `mypy` when available).
4. Open the pull request and fill in the template. CI must pass (the `lint` job is allowed
   to fail while the baseline above is being worked down).

## Reporting issues

- Use the [issue forms](.github/ISSUE_TEMPLATE) for bugs and feature requests.
- Do **not** open a public issue for a security vulnerability; follow
  [SECURITY.md](SECURITY.md) instead.
