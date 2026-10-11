import ast
import re
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_new_module_has_the_function():
    from _pytest._classcheck import safe_isclass
    assert safe_isclass(int) is True and safe_isclass(3) is False


def test_old_import_still_works_but_warns():
    from _pytest import compat
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        assert compat.safe_isclass(int) is True
    assert any(issubclass(x.category, DeprecationWarning) for x in w)


def test_internal_code_and_tests_use_the_new_module():
    bad = []
    for d in ("src", "testing"):
        for f in (ROOT / d).rglob("*.py"):
            text = f.read_text(errors="ignore")
            if "safe_isclass" not in text or f.name in ("_classcheck.py", "compat.py"):
                continue
            for node in ast.walk(ast.parse(text)):
                if isinstance(node, ast.ImportFrom) and any(a.name == "safe_isclass" for a in node.names):
                    if node.module != "_pytest._classcheck":
                        bad.append(f"{f.relative_to(ROOT)} imports from {node.module}")
    assert not bad, bad
