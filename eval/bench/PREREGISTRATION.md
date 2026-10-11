# Big-repo benchmark: pre-registered question and decision rule

Written before any model run on these tasks (commit date is the evidence). Do not edit after results exist; add a
dated "Deviations" section instead.

**Question.** On a real 100k-line repo (pinned pytest checkout, tasks `big_move_realfunc`, `big_move_isclass`), does the
full ctxrelay handoff with its graph/MCP tools (C3) beat the same handoff as a plain file (C4) and a naive prose
handoff (C2)? Both tasks contain a requirement only the previous session knew (written in the notes, not the task text).

**Design.** Codex as the continuing model (Claude as a second model if budget allows). Conditions C0 cold, C2 naive,
C3 ctxrelay + MCP, C4 handoff file only. 3 repeats per cell. A run succeeds iff the hidden tests and the visible test
subset pass with no collateral edits. Tool calls = command executions + MCP calls + file changes. Uncached tokens =
input minus cached input.

**Decision rule (applies to the pooled runs of both tasks).**
1. If C3 does not have a strictly higher success rate than C4, **and** does not use at least 25% fewer tool calls
   than C4 at equal success, then MCP/graph is not shown to help: demote it to optional, lead the README with the
   file handoff, and say so.
2. If C3 has higher success or >=25% fewer tool calls than C4, but more than 1.5x the uncached tokens, report it as a
   trade-off rather than a win.
3. If C4 and C3 are not clearly better than C0 on success, the benchmark has not shown that handoffs help on large
   repos; say that.
4. Whatever the outcome, report every run, including failures with the reason (`hidden_tail` in the result JSON).

**Known limits.** The previous session is scripted, so C2-C4 get identical facts. Two tasks, one repo, Python only.
Results show direction, not significance.
