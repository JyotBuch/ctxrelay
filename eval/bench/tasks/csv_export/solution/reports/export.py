import csv


def _safe(v):
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@"):
        return "'" + v
    return v


def export_csv(rows, path):
    """Write a list of dicts as CSV; header comes from the first row."""
    rows = list(rows)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(rows[0].keys())
        for r in rows:
            w.writerow([_safe(v) for v in r.values()])
