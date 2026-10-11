"""Re-run graph_eval with the v1 matching rules (identifiers anywhere, including comments/strings; no
method/top-level distinction) to compare against the current graph on the identical, edge-independent sample.
usage: python eval/graph_eval_legacy.py <repo> [args]   (writes eval/results/graph_<repo>.json: copy it first)"""
import re
import runpy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from ctxrelay import graph

_defs = graph._defs
graph._defs = lambda rel, text: ((n, k, l, False) for n, k, l, _m in _defs(rel, text))
graph._tokens = lambda rel, text: ((i, m.group(0), False) for i, line in enumerate(text.splitlines(), 1)
                                   for m in re.finditer(r"[A-Za-z_]\w{2,}", line))
sys.argv[0] = str(Path(__file__).parent / "graph_eval.py")
runpy.run_path(sys.argv[0], run_name="__main__")
