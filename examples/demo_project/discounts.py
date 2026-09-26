"""Discount codes for the demo cart app. SAVE10 = 10% off, SAVE20 = 20% off."""

DISCOUNTS = {
    "SAVE10": 10,
    "SAVE20": 20,
}


def discount_pct(code):
    """Return the percent off for a discount code, or 0 if no code was given.

    BUG: an unknown code (anything not in DISCOUNTS) raises KeyError instead of
    being treated as "no discount" -- it should warn and fall back to 0.
    """
    if not code:
        return 0
    return DISCOUNTS[code]
