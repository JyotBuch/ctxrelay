from shop.catalog import Catalog
from shop.pricing import CALLS, price_with_tax


def test_repeat_call_is_cached():
    c = Catalog({"a": 10.0})
    price_with_tax(c, "a")
    n = CALLS["n"]
    assert price_with_tax(c, "a") == 12.0
    assert CALLS["n"] == n


def test_never_stale_after_update():
    c = Catalog({"a": 10.0})
    assert price_with_tax(c, "a") == 12.0
    c.update("a", 20.0)
    assert price_with_tax(c, "a") == 24.0


def test_separate_catalogs_do_not_collide():
    a, b = Catalog({"x": 1.0}), Catalog({"x": 2.0})
    assert price_with_tax(a, "x") == 1.2 and price_with_tax(b, "x") == 2.4
