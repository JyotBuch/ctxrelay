# Changelog

## 0.2.0
- Automatic capture of verified work: edits, test runs, failures and commits since the task started, from Claude
  Code hooks (`ctxrelay init --hooks`) or recovered from Claude Code / Codex session transcripts (`ctxrelay ingest`).
- Handoff gains "Verified work" and "Exact next action" sections and a `hypothesis` note kind.
- `ctxrelay switch` validates the destination CLI and its MCP registration, refreshes the graph, verifies the handoff,
  prints a summary of what transfers, and has `--dry-run`.
- Graph builds cache per-file parses, so unchanged files are not re-parsed.
- Terminal UI: styled `init` / `switch`, and a status screen for bare `ctxrelay` / `ctxrelay status`.
- `ctxrelay doctor` checks the setup and prints exact fixes.
- Rules written to `AGENTS.md` no longer ask models to log progress notes (it cost tokens without helping).
- Benchmark harness in `eval/bench` and first results in `eval/RESULTS.md`.

## 0.1.0
- Task notes, SQLite code graph, MCP server, `ctxrelay switch`, evaluation harness.
