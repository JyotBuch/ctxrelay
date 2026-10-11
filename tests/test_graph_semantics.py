"""Locks in the graph's matching rules on a fixture whose true answers are known by construction.

If you change graph.py on purpose, update the fixture and say why in the PR. For accuracy on real repos see
eval/ (the `eval-regression` workflow guards that).
"""
import textwrap

import pytest

from ctxrelay import graph


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def w(name, body):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(body))

    w("core.py", """
        def compute_total(items):
            return sum(items)

        def unused_helper():
            return 0

        def tiny(): pass
        def ab(): pass

        class Ledger:
            def record(self, x):
                return compute_total([x])
    """)
    w("service.py", """
        import core
        from core import compute_total

        def run_service():
            # compute_total appears only in this comment, so must not count by itself
            return compute_total([1])

        def via_module():
            return core.compute_total([2])

        def in_string_only():
            return "unused_helper is only mentioned in this string"

        def in_comment_only():
            # unused_helper() would be called here someday
            return 1

        def calls_method(ledger):
            return ledger.record(3)

        def bare_record():
            record = 1          # a local variable that merely shares a method's name
            return record
    """)
    # same name defined in 6 files -> too ambiguous to link
    for i in range(6):
        w(f"dup{i}.py", "def process():\n    return 1\n")
    w("user.py", "def use_dup():\n    return process()\n")
    w("broken.py", "def broken(:\n    pass\n")                       # syntax error: must not crash the index
    w("web/app.ts", """
        export function renderPage() { return helperFn(); }
        const helperFn = () => 1;
        // renderPage in a comment
        const s = "renderPage in a string";
    """)
    w("main.go", "package main\nfunc ServeAll() { renderPage() }\n")
    graph.build(tmp_path)
    return tmp_path


def callers(name):
    return {line.split()[0] for line in graph.callers(name).splitlines() if line != "(none)"}


def test_real_calls_are_found(repo):
    assert callers("compute_total") == {"record", "run_service", "via_module"}


def test_method_call_via_attribute(repo):
    assert "calls_method" in callers("record")


def test_comments_and_strings_do_not_create_edges(repo):
    assert callers("unused_helper") == set()


def test_bare_name_does_not_link_to_method(repo):
    assert "bare_record" not in callers("record")


def test_names_defined_in_many_places_are_skipped(repo):
    assert callers("process") == set()


def test_short_names_are_ignored(repo):
    assert callers("tiny") == set() and callers("ab") == set()


def test_typescript_arrow_and_function(repo):
    assert callers("helperFn") == {"renderPage"}
    # Go calling a same-named symbol links across languages (name-based by design); the comment and string
    # mentions of renderPage in app.ts add nothing
    assert callers("renderPage") == {"ServeAll"}


def test_syntax_error_file_does_not_crash_and_is_indexed_by_fallback(repo):
    assert "broken" in graph.find("broken")


def test_impact_is_transitive(repo):
    assert {"run_service", "via_module"} <= callers("compute_total")
    impact = {line.split()[0] for line in graph.impact("compute_total").splitlines()}
    assert {"record", "calls_method"} <= impact


def test_index_is_deterministic(repo):
    def snapshot():
        con = graph.connect()
        return (con.execute("SELECT name,file,line,method FROM symbols ORDER BY id").fetchall(),
                con.execute("SELECT src,dst FROM edges ORDER BY src,dst").fetchall(),
                con.execute("SELECT path,community FROM files ORDER BY path").fetchall())
    first = snapshot()
    graph.build(repo)
    assert snapshot() == first


def test_ignored_directories_are_not_indexed(repo):
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "x.js").write_text("function leaked() {}\n")
    graph.build(repo)
    assert "leaked" not in graph.find("leaked")
