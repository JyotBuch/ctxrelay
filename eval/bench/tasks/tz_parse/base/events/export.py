from .timeparse import parse_ts


def export_row(s):
    return parse_ts(s).strftime("%d/%m/%Y %H:%M")


def legacy_age_seconds(s, now):
    """`now` is a naive datetime."""
    return int((now - parse_ts(s)).total_seconds())
