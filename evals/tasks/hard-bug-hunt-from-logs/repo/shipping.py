"""Flat-rate-ish shipping estimate."""


def estimate_shipping(order):
    weight_units = sum(item.quantity for item in order.items)
    return round(2.5 + 0.5 * weight_units, 2)
