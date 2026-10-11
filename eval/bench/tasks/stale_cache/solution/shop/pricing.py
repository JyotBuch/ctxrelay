CALLS = {"n": 0}
_CACHE = {}


def price_with_tax(catalog, sku, rate=0.2):
    key = (id(catalog), catalog.version, sku, rate)
    if key not in _CACHE:
        CALLS["n"] += 1
        _CACHE[key] = round(catalog.get(sku) * (1 + rate), 2)
    return _CACHE[key]
