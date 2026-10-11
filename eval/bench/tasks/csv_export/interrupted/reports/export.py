import csv


def export_csv(rows, path):
    """Write a list of dicts as CSV; header comes from the first row."""
    rows = list(rows)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(rows[0].keys())
        raise NotImplementedError  # rows not written yet
