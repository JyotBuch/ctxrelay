# ctxrelay evaluation results

Plan: see the test plan. This file records measured results only. Status: **Eval 1 done for Python and TypeScript (graph v3);
Eval 2 done for Claude Code and Codex (Gemini dropped by the user); Eval 3 not yet run.** Go is deferred (no Go toolchain installed).

## Eval 1: graph quality (`python eval/graph_eval.py <repo>`; `graph_eval_legacy.py` reruns the v1 rules)

Repos pinned in `repos.toml`. Ground truth is file-level: which files reference a top-level function/class, from
jedi (Python) and the TypeScript language service (TS). 60 symbols per repo, stratified into hub/mid/leaf by how
many files contain the name as a word (independent of the graph, so **the sample is identical across graph
versions**), seed 1. Methods are excluded because neither tool can infer dynamic receivers. Tests, docs, examples
and scripts are excluded from the sample.

Graph versions: **v1** = any identifier token links to any same-named definition. **v3 (current)** = identifiers in
comments and strings are ignored (tokenizer for Python, comment/string stripping for other languages), and a bare
`name` can't link to a method. v2 also blocked `x.name` from reaching top-level defs; it cut recall (0.92 to 0.81
on pytest) because `mod.func()` calls were lost, so v3 reverted that part.

| | pytest v1 | pytest v3 | nest v1 | nest v3 |
|---|---|---|---|---|
| Index build | 1.4 s | 1.9 s | 0.7 s | 0.9 s |
| Edges | 84,751 | 43,369 | 18,629 | 13,311 |
| Callers precision | 0.71 | **0.76** | 0.58 | **0.60** |
| Callers recall | 0.92 | 0.92 | 0.89 | **0.95** |
| F1, all | 0.73 | **0.76** | 0.60 | **0.63** |
| F1, names defined once (n=28 / 36) | 0.88 | **0.91** | 0.65 | **0.68** |
| F1, names defined 2+ times | 0.60 | 0.63 | 0.53 | 0.55 |
| F1 hub / mid / leaf | 0.67 / 0.65 / 0.87 | 0.70 / 0.67 / 0.91 | 0.64 / 0.37 / 0.80 | 0.67 / 0.42 / 0.80 |

Bar from the plan (callers F1 >= 0.7 on names defined once): **met on pytest (0.91), not met on nest (0.68).**
(An earlier run reported nest at 0.79; that used a different sample selected by the graph's own edge counts and
is superseded.)

What this says:
- The cleanup roughly halves the edge count and helps both repos by 0.02-0.03 F1 without losing recall. It is a
  modest improvement, not a transformation. One seed and 60 symbols per repo, so differences of 0.02-0.03 are
  within noise; the clearer signals are the halved edge count and unchanged recall.
- Recall is high (0.92-0.95): the graph rarely misses a real dependent file. Precision is the weakness (0.60-0.76),
  most of all for names defined in several places and for mid-popularity symbols.
- Remaining false edges are almost all bare identifiers that collide with another binding of the same name
  (209 of 216 in nest after cleanup). Fixing that needs import resolution (tree-sitter or real import parsing)
  so a name only links to a definition the file can actually see.
- **The nest numbers are pessimistic.** For several symbols (for example the `Controller` decorator) tsc reports
  zero references in `integration/` apps even though those files import and use them (checked by hand), so real
  usages are counted as false edges. Nest's tsconfig isn't resolving those imports. Treat nest precision as a lower
  bound until the ground truth is repaired.

Other caveats:
- Ground truth tools have gaps (they reported 0 references for some methods, which is why methods are excluded).
  F1 is a relative measure, not absolute.
- Speed is proven only at this size (about 2 s for 274-2012 files); not tested on 1M+ lines.

## Eval 2: integration (run against real CLIs, throwaway repo)

Run headless with per-run MCP config so no global config was changed. Gemini is out of scope (not installed).

| Check | Claude Code 2.1.296 | Codex 0.162.1 |
|---|---|---|
| MCP server connects, `graph_callers` returns correct output | pass | pass |
| `handoff_note` persists to `.ctxrelay/state.json` | pass | pass |
| Rules in `AGENTS.md` reach the model | pass (via `CLAUDE.md` `@AGENTS.md` import; model quoted the rule) | pass (reads `AGENTS.md` directly; model quoted the rule) |
| `ctxrelay switch` builds a valid launch command | pass: `claude [prompt]` is the documented usage | argv matches `codex [PROMPT]` usage; not launched |

- **Codex needed two things.** (1) Upgrading from 0.36.0, whose default model was rejected by the server for an
  outdated CLI. (2) Headless `codex exec` blocks MCP tool calls ("requires approval, but approval policy is never")
  until the server is trusted with `mcp_servers.ctxrelay.default_tools_approval_mode = "approve"`. Interactive
  sessions just prompt. The README now says so.
- **Cost datapoint for Eval 3:** one trivial Codex run used about 60k input tokens (about 54k cached) even
  for a 3-file repo, so per-run overhead is not small.
- **Not verified:** the interactive launch of `ctxrelay switch claude|codex` (interactive, not run headless).
- **Robustness (automated, in `tests/`):** the MCP server answers every request and survives malformed
  JSON, unknown tools and methods, a missing index, and an invalid note kind; every listed tool is callable.
  `switch print` in a non-git directory and a missing binary behave sensibly.

## Eval 3: pilot (`python eval/e2e/pilot.py`), n=1 per condition. Directional only.

Task: move `fnmatch_ex` from `src/_pytest/pathlib.py` into a new module and update imports in 6 files (pytest repo,
pinned SHA). Stage A: Claude Code, cut off by `--max-turns 4` after it created the new module (5 of 6 files still
wrong). Stage B: Codex 0.162.1 continues from the identical interrupted tree. Success = definition moved, no alias
left, every file imports from the new module, no collateral edits, imports and targeted tests pass.

| Condition | Success | Input tokens | Output tokens | Commands | MCP calls | Wall |
|---|---|---|---|---|---|---|
| C0 cold (task restated) | yes | 145,516 | 1,505 | 6 | 0 | 44 s |
| C1 git status/diff pasted in | yes | 129,215 | 1,155 | 5 | 0 | 37 s |
| C3 ctxrelay handoff + graph | yes | 465,824 | 2,289 | 10 | 6 | 95 s |

What this shows: **nothing in favour of ctxrelay yet.** All three succeeded, so the task is too easy to separate
conditions (ceiling effect). C3 used about 3x the input tokens and twice the wall time, because Codex made extra
graph and handoff calls on a 6-file change that `grep` solves directly. On small tasks the overhead is a cost, not
a saving. Single runs are noisy, so treat the size of the gap as uncertain.

Harness findings:
- A turn cap is a coarse way to interrupt: Claude batches edits in parallel, so `move_abspath` (10 files) did
  nothing at 3 turns and finished everything at 4. Only `move_fnmatch` produced a valid mid-task interruption.
- Claude's own notes were good when it got far enough (it recorded the goal, constraint, decision and the rejected
  alias without prompting), but at the 4-turn cutoff it had recorded only the goal, so the handoff added little
  beyond the git diff.
- A real test of the claim needs tasks that are genuinely hard without prior context (large repos, many files, a
  non-obvious trap that was already discovered), more repeats, and interruption by tokens or a scripted point
  rather than a turn count.

## colgrep comparison (`python eval/colgrep_eval.py`), pytest `src/` only (81 files)

colgrep 1.8.5 (LateOn-Code-edge model), index built in 45 s, about 0.6 s per query. Run with `HF_HOME` pointed at a clean
directory because a stale stored Hugging Face token made the public model download fail with a 401.

**Discovery** ("find the code that does X"): 50 top-level symbols with docstrings, each described by a Claude-written
paraphrase that avoids the name and docstring wording. Target = the file defining the symbol.

| System | hit@1 | hit@3 | hit@5 | hit@10 | MRR |
|---|---|---|---|---|---|
| colgrep | **0.64** | **0.82** | **0.92** | **1.00** | **0.76** |
| BM25 over files (keyword baseline) | 0.50 | 0.74 | 0.80 | 0.96 | 0.65 |
| ctxrelay `graph find` (name substring) | 0.30 | 0.48 | 0.58 | 0.74 | 0.42 |
| colgrep, exact symbol rather than file | 0.42 | 0.58 | 0.66 | 0.74 | 0.53 |

**Structure** (callers of a symbol, file-level, vs jedi, 60 symbols from the Eval 1 sample, `src/` only):

| System | Precision | Recall | F1 |
|---|---|---|---|
| ctxrelay graph | **0.71** | 0.93 | **0.70** |
| colgrep `called_by` (names mapped to files) | 0.53 | 0.81 | 0.54 |
| plain `grep -w` | 0.44 | 1.00 | 0.45 |

Reading it:
- colgrep is clearly better than ctxrelay at discovery. ctxrelay's only discovery is a name substring match, which
  is the wrong tool for natural-language questions. This is a real gap in ctxrelay.
- ctxrelay's graph is better than colgrep's `called_by` for callers, and both beat plain grep on precision. So the
  two are complementary: colgrep to find where to look, the graph for what depends on it.
- Caveats: only 81 files (a small search space, which flatters every system at hit@10); one repo; one set of
  Claude-written queries that may still echo docstring ideas; colgrep did not return the exact symbol for 16 of
  the 60 structure lookups (its `called_by` was empty there, which lowers its score); colgrep's `called_by`
  gives caller names, not files, so mapping names to files adds ambiguity; and colgrep indexed `src/` only, so
  all structure scoring ignores tests.
