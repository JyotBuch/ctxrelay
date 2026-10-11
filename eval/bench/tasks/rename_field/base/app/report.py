from .api import user_json


def summary(rows):
    return ", ".join(f"{u['user_id']}:{u['name']}" for u in map(user_json, rows))
