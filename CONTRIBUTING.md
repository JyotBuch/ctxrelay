# Contributing

```sh
pip install -e ".[dev]" pytest-cov
make check        # ruff, mypy, pytest with a coverage floor
```

## What CI checks, and why

| Check | Guards against |
|---|---|
| `ruff` | Bugs and hygiene: unused code, shadowed names, bad imports. Style opinions are left to review. |
| `mypy` | Type mistakes in `ctxrelay/` |
| `pytest` on Linux and macOS, Python 3.9 / 3.12 / 3.13 | Behavior and portability. Coverage must stay at or above 80%. |
| `tests/test_graph_semantics.py` | Silent changes to how the graph links symbols (a fixture with exactly known answers) |
| `tests/test_structure.py` | Drift: README commands that don't exist, MCP tools missing a description, an added dependency or network import, a version mismatch, a non-idempotent `init` |
| `package` job | A wheel that doesn't install, or ships tests or data. Installs it clean and runs the CLI and MCP server. |
| `eval-regression` | Real-world accuracy: re-measures pytest and NestJS against `eval/thresholds.json` (on graph or eval changes, weekly, and on demand) |
| `gitleaks`, `CodeQL`, `actionlint`, Dependabot | Leaked secrets, security patterns, broken workflows, stale actions and dependencies |

## When you add or change something

- **New CLI command or MCP tool:** add a test. The structure tests already require a help text, a tool description
  and a valid schema, and fail if the README mentions a command that doesn't exist.
- **New dependency:** ctxrelay is stdlib-only on purpose. Adding one needs a reason in the PR, and a change to
  `test_no_runtime_dependencies`.
- **Change to graph matching:** update the fixture in `tests/test_graph_semantics.py`, run the eval, and keep
  `eval/thresholds.json` passing. If you raise accuracy, raise the thresholds too, so it can't slip back.
- **New language or ground-truth repo:** add it to `eval/repos.toml` (pinned SHA) and `eval/thresholds.json`.
- **Updating a CLI integration (Claude Code, Codex):** re-run the manual smoke checks in `eval/RESULTS.md`; CI can't
  run the real clients.

## What CI does not check

It can't run the real Claude Code or Codex clients, and it doesn't verify that README result tables match
`eval/results/`. Update those by hand, as the PR checklist says.
