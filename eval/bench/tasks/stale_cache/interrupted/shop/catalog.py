class Catalog:
    def __init__(self, prices):
        self._prices = dict(prices)
        self.version = 0

    def get(self, sku):
        return self._prices[sku]

    def update(self, sku, price):
        self._prices[sku] = price
        self.version += 1
