from shop.catalog import Catalog
from shop.pricing import price_with_tax


def test_price_with_tax():
    assert price_with_tax(Catalog({"a": 10.0}), "a") == 12.0
