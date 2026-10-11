## What and why

## Checklist
- [ ] `make check` passes locally (lint, types, tests)
- [ ] New behavior has a test; a changed graph rule updates `tests/test_graph_semantics.py` and says why
- [ ] If this can change graph accuracy: ran `python eval/graph_eval.py pytest` and `nest`, and `eval/check_thresholds.py` passes
- [ ] If numbers moved: updated `eval/RESULTS.md` and the README tables (CI does not check these match)
- [ ] If a threshold was lowered in `eval/thresholds.json`, the reason is in this description
- [ ] README and `AGENTS.md` rules still describe real commands and tools
