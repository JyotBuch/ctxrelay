from pathlib import Path

from app import api, models, report


def test_json_uses_account_id():
    con = models.connect()
    models.add_user(con, 7, "bo")
    out = api.user_json(models.get_user(con, 7))
    assert out == {"account_id": 7, "name": "bo"}


def test_request_accepts_both_names():
    assert api.parse_request({"account_id": 3}) == 3
    assert api.parse_request({"user_id": 4}) == 4


def test_report_works():
    assert report.summary([(1, "ann")]) == "1:ann"


def test_migration_is_frozen():
    sql = (Path(__file__).resolve().parent.parent / "migrations" / "001_init.sql").read_text()
    assert "user_id" in sql and "account_id" not in sql
