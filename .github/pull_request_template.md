## What does this PR change?

<!-- What and why. Link the issue: Closes # -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Documentation / engineering setup
- [ ] Breaking change (describe the migration path in CHANGELOG; MAJOR-level per SemVer)

## Verification

- [ ] `.venv/bin/python -m pytest tests/ -q` passes
- [ ] Ran `ruff check .` and `mypy src` where the tools are available
- [ ] New code does not add to the lint/type baseline (see CONTRIBUTING.md)
- [ ] Recorded in the `[Unreleased]` section of `CHANGELOG.md`

## Behaviour boundaries

- [ ] No network access was added by default (only the explicit `--update-pricing` path may use it)
- [ ] The user's local session and pricing files are not written to, modified or deleted
- [ ] Charts are still rendered in memory and never written to disk; data still goes to
      stdout and diagnostics to stderr
- [ ] If `--json` / `--schema` output changed, the compatibility impact is documented

## Notes

<!-- Screenshots, terminal mode, test output, or anything reviewers should look at closely -->
