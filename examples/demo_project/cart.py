"""Cart total math for the demo project. Has two real, findable bugs -- see discounts.py too."""
from discounts import discount_pct


def subtotal(items):
    return sum(item["price"] * item["qty"] for item in items)


def apply_discount(amount, code):
    """Apply a discount code's percent-off to `amount`.

    BUG: `pct` is a whole number like 10 (meaning 10%), but this subtracts
    `amount * pct` instead of `amount * pct / 100` -- SAVE10 wipes out 1000% of
    the total instead of 10%, driving it deeply negative.
    """
    pct = discount_pct(code)
    return amount - amount * pct


def total(items, code=None):
    return round(apply_discount(subtotal(items), code), 2)
