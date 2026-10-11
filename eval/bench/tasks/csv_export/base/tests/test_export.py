from reports.export import export_csv


def test_basic(tmp_path):
    p = tmp_path / "o.csv"
    export_csv([{"name": "ann", "n": 3}, {"name": "bo", "n": 4}], p)
    assert p.read_text().splitlines() == ["name,n", "ann,3", "bo,4"]
