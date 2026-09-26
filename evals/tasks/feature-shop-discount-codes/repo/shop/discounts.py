class DiscountCode:
    """
    kind: "percent" or "fixed"
    value: for "percent", a number 0-100 meaning percent off the subtotal.
           for "fixed", a flat dollar amount off the subtotal.
    min_spend: the cart subtotal (before discount) must be >= this for
               the code to apply. Defaults to 0 (always eligible).
    """

    def __init__(self, code, kind, value, min_spend=0.0):
        if kind not in ("percent", "fixed"):
            raise ValueError(f"Unknown discount kind: {kind!r}")
        self.code = code
        self.kind = kind
        self.value = value
        self.min_spend = min_spend
