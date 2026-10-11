from .api import user_json


def summary(rows):
    return ", ".join(f"{u['account_id']}:{u['name']}" for u in map(user_json, rows))
