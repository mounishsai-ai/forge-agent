"""Computes final order totals, including tag-based promotional discounts."""


def apply_tag_discounts(order):
    """Each tag on the order knocks 5% off the subtotal (tags stack additively)."""
    order.discount_percent = len(order.tags) * 5


def compute_total(order):
    subtotal = round(sum(item.subtotal for item in order.items), 2)
    discount = round(subtotal * order.discount_percent / 100, 2)
    total = round(subtotal - discount, 2)
    if total < 0:
        raise ValueError(
            f"order {order.order_id}: computed total {total} is negative "
            f"(subtotal={subtotal}, discount_percent={order.discount_percent})"
        )
    return total
