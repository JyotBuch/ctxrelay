def user_json(row):
    return {"account_id": row[0], "name": row[1]}


def parse_request(d):
    return d["account_id"] if "account_id" in d else d["user_id"]
