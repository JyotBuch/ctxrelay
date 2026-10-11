from __future__ import annotations

import functools
import inspect


def get_real_func(obj):
    """Get the real function object of the (possibly) wrapped object by
    :func:`functools.wraps`, or :func:`functools.partial`."""
    obj = inspect.unwrap(obj)

    if isinstance(obj, functools.partial):
        obj = obj.func
    return obj
