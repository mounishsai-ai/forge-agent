"""Adds promotional tags to orders based on simple business rules."""


def tag_order(order):
    """Add a 'bulk' tag for orders with 3 or more line items; used by the
    pipeline before pricing."""
    if len(order.items) >= 3:
        order.tags.append("bulk")
    return order
