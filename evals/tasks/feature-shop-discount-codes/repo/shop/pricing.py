def calculate_total(cart, registry):
    """
    Compute the final total for a cart.

    - Start from cart.subtotal() (sum of item subtotals).
    - If cart.discount_code is None, the total is just the subtotal.
    - Otherwise, look up cart.discount_code in `registry`, a dict mapping
      code strings to DiscountCode objects. The lookup is case-insensitive
      and ignores leading/trailing whitespace on the cart's code (e.g. a
      cart code of " Save10 " matches a registry key of "SAVE10").
    - If the code is not found in the registry (after normalizing), raise
      ValueError(f"Unknown discount code: {cart.discount_code}").
    - If the code IS found but the cart's subtotal is less than the
      code's min_spend, the code does not apply: the total is just the
      subtotal (no error raised).
    - If the code applies:
        - kind "percent": subtract subtotal * (value / 100) from the total.
        - kind "fixed": subtract value (a flat dollar amount) from the total.
      The discount can never push the total below 0 (clamp at 0).
    - The final total is rounded to 2 decimal places.

    Only one discount code can be active on a cart at a time (Cart stores
    a single discount_code string, not a list), so there is no stacking
    logic to implement.
    """
    raise NotImplementedError
