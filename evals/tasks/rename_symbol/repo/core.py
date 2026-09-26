"""Core arithmetic helpers used across the mini order-processing app."""


def calc_total(items):
    """Return the total price for a list of {'price': float, 'qty': int} dicts."""
    return sum(item["price"] * item["qty"] for item in items)
