CALLS = {"n": 0}


def price_with_tax(catalog, sku, rate=0.2):
    CALLS["n"] += 1
    return round(catalog.get(sku) * (1 + rate), 2)
