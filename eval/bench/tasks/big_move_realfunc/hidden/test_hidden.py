import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYM, NEW, OLD_FILE = "get_real_func", "_pytest._realfunc", "src/_pytest/compat.py"


def py_files():
    for d in ("src", "testing"):
        yield from (ROOT / d).rglob("*.py")


def test_defined_only_in_the_new_module():
    assert re.search(rf"^def {SYM}\b", (ROOT / "src/_pytest/_realfunc.py").read_text(), re.M)
    assert not re.search(rf"^def {SYM}\b", (ROOT / OLD_FILE).read_text(), re.M)


def test_every_importer_uses_the_new_module_not_compat():
    bad = []
    for f in py_files():
        text = f.read_text(errors="ignore")
        if not re.search(rf"\b{SYM}\b", text) or f.name == "_realfunc.py" or str(f).endswith(OLD_FILE):
            continue
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ImportFrom) and any(a.name == SYM for a in node.names):
                if node.module != NEW:
                    bad.append(f"{f.relative_to(ROOT)} imports from {node.module}")
    assert not bad, bad


def test_package_still_imports():
    r = subprocess.run([sys.executable, "-c", "import _pytest.config, _pytest.python, _pytest.fixtures, _pytest._code"],
                       capture_output=True, text=True, env={"PYTHONPATH": str(ROOT / "src"), "PATH": ""})
    assert r.returncode == 0, r.stderr
