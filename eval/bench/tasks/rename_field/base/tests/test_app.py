from app import api, models, report


def test_roundtrip():
    con = models.connect()
    models.add_user(con, 1, "ann")
    row = models.get_user(con, 1)
    assert api.user_json(row)["name"] == "ann"
    assert report.summary([row]) == "1:ann"
