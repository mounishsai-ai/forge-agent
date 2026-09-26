"""Fake stock reservation (in-memory)."""

_stock = {}


def reserve_stock(order):
    for item in order.items:
        _stock[item.sku] = _stock.get(item.sku, 1000) - item.quantity
    return True
