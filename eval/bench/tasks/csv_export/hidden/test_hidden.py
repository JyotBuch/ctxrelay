from reports.export import export_csv


def read(p):
    return p.read_text().splitlines()


def test_formula_cells_are_neutralised(tmp_path):
    p = tmp_path / "o.csv"
    export_csv([{"a": "=SUM(A1:A2)", "b": "@cmd", "c": "+1", "d": "-x", "e": "ok"}], p)
    assert read(p)[1] == "'=SUM(A1:A2),'@cmd,'+1,'-x,ok"


def test_numbers_are_not_altered(tmp_path):
    p = tmp_path / "o.csv"
    export_csv([{"n": -5, "f": -1.5, "s": "plain"}], p)
    assert read(p)[1] == "-5,-1.5,plain"
