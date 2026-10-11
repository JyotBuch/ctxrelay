from __future__ import annotations

import inspect


def safe_isclass(obj: object) -> bool:
    """Ignore any exception via isinstance on Python 3."""
    try:
        return inspect.isclass(obj)
    except Exception:
        return False
