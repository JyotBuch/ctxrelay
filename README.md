# ctxrelay

[![CI](https://github.com/JyotBuch/ctxrelay/actions/workflows/ci.yml/badge.svg)](https://github.com/JyotBuch/ctxrelay/actions/workflows/ci.yml)

Keep your task and codebase context portable when you switch between coding-agent subscriptions
(Claude Code, Codex CLI; Gemini CLI untested) because one hit its usage limit.

Two problems, two pieces:

1. **Task state doesn't survive a switch.** Transcripts carry hidden reasoning, tool state and provider-specific
   formatting that don't transfer. ctxrelay keeps a small model-agnostic record instead: goal, constraints,
   decisions, rejected options, open questions, next steps. It adds live git state and renders `HANDOFF.md`.
2. **Codebase understanding doesn't survive a switch.** The new model would re-read files to relearn the
   architecture, which burns the limit you're trying to stretch. ctxrelay indexes the repo into a SQLite
   graph and serves narrow queries (callers, impact, communities, hubs) over MCP, so the answer costs a few
   hundred tokens instead of a pile of file reads. Any MCP-capable CLI can use it.

**What it deliberately does not do:** rotate or proxy subscription OAuth tokens. Anthropic has restricted
using Free/Pro/Max tokens outside its own clients, and other providers' terms on pooling accounts are
unclear. You stay in the official CLIs and ctxrelay only hands context across.

## Install

```sh
git clone https://github.com/JyotBuch/ctxrelay && cd ctxrelay
pip install -e .        # Python 3.9+, no dependencies
```

## Use

```sh
cd your-project
ctxrelay init           # writes AGENTS.md rules (+ CLAUDE.md/GEMINI.md importing it), builds the graph
claude mcp add ctxrelay -- ctxrelay serve     # once per tool
codex mcp add ctxrelay -- ctxrelay serve
gemini mcp add ctxrelay ctxrelay serve
```

Headless `codex exec` refuses MCP tool calls that need approval. To let it use ctxrelay, add to `~/.codex/config.toml`:

```toml
[mcp_servers.ctxrelay]
default_tools_approval_mode = "approve"
```

While you work, agents record state with the `handoff_note` tool (the rules in `AGENTS.md` tell them to).
You can also do it yourself:

```sh
ctxrelay note decision "Use SQLite, not Postgres: single-user tool"
ctxrelay note rejected "Redis cache: no measured need"
ctxrelay note next "Wire the retry logic into client.py"
```

When a limit is close:

```sh
ctxrelay switch codex --reindex    # writes .ctxrelay/HANDOFF.md, refreshes graph, launches codex with a prompt to read it
ctxrelay switch claude             # or gemini; `ctxrelay switch print` just prints the handoff
```

Query the graph directly: `ctxrelay q find|callers|callees|impact|file|community|hubs [arg]`.

Find code by description when you don't know a name: `ctxrelay q search "load settings from an ini file"`
(also the `search_code` MCP tool). This needs [colgrep](https://github.com/lightonai/next-plaid)
(`brew install lightonai/tap/colgrep`); ctxrelay works without it. The first search indexes the project, which can
take a minute on a large repo. If colgrep fails with a 401 downloading its model, a stale Hugging Face token is
usually the cause: retry with `HF_HOME` set to an empty directory.

ctxrelay is more than an MCP server. The graph and note tools are exposed over MCP, but the `AGENTS.md` rules and
`HANDOFF.md` (which includes a short code map) are plain files that work without it, and `ctxrelay switch` is a
launcher that MCP can't replace.

## Evaluation: what was measured and how to read it

Full tables, caveats and raw data: `eval/RESULTS.md` and `eval/results/`. Repos are pinned by commit in
`eval/repos.toml`. Reproduce with `eval/fetch.sh`, then `python eval/graph_eval.py pytest` (or `nest`) and
`python eval/e2e/pilot.py`, `python eval/colgrep_eval.py discovery|structure`.

### Graph accuracy (does `callers` / `impact` find the right files?)

For 60 sampled top-level functions and classes per repo, the graph's answer is compared with a real language tool
as ground truth (jedi for Python, the TypeScript compiler for TypeScript), at file level.

| Metric | Meaning | Why it matters |
|---|---|---|
| **Recall** | Of the files that really depend on a symbol, the share the graph found | Low recall means silently missed dependents: the riskier error |
| **Precision** | Of the files the graph reported, the share that really depend on it | Low precision means extra files to rule out: costs time and tokens, not correctness |
| **F1** | One number combining the two (1.0 = perfect) | Use it to compare graph versions, not as an absolute grade |
| **Tiers** (hub / mid / leaf) | Symbols with many / some / few users | Hubs are the queries where you most want the answer to be right |
| **Name defined once vs 2+ times** | Same-named symbols are the hard case, so they are reported separately | Expect worse numbers when names collide |

Current results (graph v3):

| | pytest (Python) | nest (TypeScript) |
|---|---|---|
| Recall | 0.92 | 0.95 |
| Precision | 0.76 | 0.60 |
| F1, names defined once | 0.91 | 0.68 |
| Index time (full rebuild) | about 2 s | about 1 s |

How to read this:
- **Recall is high:** the graph rarely misses a real dependent file, so it is good for narrowing a search.
- **Precision is the weak point:** treat `callers`, `impact` and `hubs` as a candidate list to check, not a guarantee.
- **The nest numbers are a lower bound:** the TypeScript checker misses some real usages there, and those are counted
  as false edges.
- **The sample is small** (one seed, 60 symbols, 2 repos), so differences of 0.02-0.03 are noise.
- Methods are excluded from scoring because neither ground-truth tool can resolve dynamic receivers.

### Finding code by description (colgrep vs the graph)

On pytest's `src/` (81 files): 50 symbols, each described by a Claude-written paraphrase that avoids the name and
docstring wording. Target = the file defining the symbol.

| System | Right file ranked first | In top 5 | In top 10 |
|---|---|---|---|
| colgrep (semantic search) | **64%** | **92%** | **100%** |
| BM25 keyword search over files | 50% | 80% | 96% |
| ctxrelay `find` (name substring) | 30% | 58% | 74% |

The same colgrep run gave the exact symbol first 42% of the time. For the other question, callers of a symbol
(60 symbols, file level, vs jedi, `src/` only):

| System | Precision | Recall | F1 |
|---|---|---|---|
| ctxrelay graph | **0.71** | 0.93 | **0.70** |
| colgrep `called_by` | 0.53 | 0.81 | 0.54 |
| plain `grep -w` | 0.44 | 1.00 | 0.45 |

How to read this: colgrep is clearly better for "where is the code that does X?" and ctxrelay's graph is better
for "what depends on X?", so they are used together (`search` for discovery, `callers`/`impact` after). Caveats: one
small repo, one set of queries, and colgrep missed the exact symbol in 16 of 60 caller lookups, which lowers its score.

### Integration

Checked against real clients (Claude Code 2.1.296, Codex 0.162.1): the MCP tools return correct results, notes persist,
and the `AGENTS.md` rules reach the model. Automated tests cover server robustness to bad input.
Not run: the interactive `ctxrelay switch` launch.

### End-to-end pilot (does a handoff help a different model finish a task?)

One task, one run per condition, so **directional only**. Claude Code was cut off mid-task, then Codex finished it:

| Condition | Succeeded | Input tokens | Wall time |
|---|---|---|---|
| Cold (task restated) | yes | 145,516 | 44 s |
| Git status/diff pasted in | yes | 129,215 | 37 s |
| ctxrelay handoff + graph | yes | 465,824 | 95 s |

How to read this:
- All three succeeded, so the task was too easy to separate them. This is **not evidence that ctxrelay helps yet**.
- The ctxrelay condition cost about 3x the tokens and twice the time: on a 6-file change, the extra handoff and
  graph calls are pure overhead. Expect the benefit, if any, on large tasks where re-learning the codebase is costly.
- A fair test needs harder tasks, several repeats and a scripted interruption point; see `eval/RESULTS.md`.

## Limits (read these)

- The graph is **heuristic**. Definitions come from Python's `ast` and regexes for other languages; edges
  come from identifier names matching defined symbols (comments and strings are ignored). It does not resolve
  imports, types or inheritance, so same-named symbols produce false edges; names defined in more than 5 places
  are skipped, as are names shorter than 3 characters. Measured on pytest and NestJS: it rarely misses a real dependent file (recall 0.92-0.95) but
  returns extra ones (precision 0.60-0.76). Treat `callers`/`impact`/`hubs` as a candidate list to check.
- `ctxrelay index` is a full rebuild: about 2 s for a 2000-file repo; untested at 1M+ lines. Add incremental indexing if it hurts.
- Communities are label propagation over the file graph, with no LLM-written labels.
- Tested against Claude Code 2.1.296 and Codex 0.162.1 (MCP tools, notes, rules pickup; see `eval/RESULTS.md`).
  The interactive `switch` launch and all Gemini commands (`gemini -i`, `gemini mcp add`) were not run: Gemini is
  untested, and the README commands for it come from its documented usage only.
- `search` depends on colgrep, a young third-party tool; its numbers above are from one repo.
- Notes are only as good as what gets recorded. If nothing is recorded, the handoff is just git state.

## Development

`make check` runs lint, types and tests. CI also tests on Linux and macOS, installs the built wheel, scans for
secrets, and re-measures graph accuracy against `eval/thresholds.json`. See `CONTRIBUTING.md` for what each check
guards and what to do when adding features.

## License

MIT. See `LICENSE`.
