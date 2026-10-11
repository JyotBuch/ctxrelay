def user_json(row):
    return {"user_id": row[0], "name": row[1]}


def parse_request(d):
    return d["user_id"]
