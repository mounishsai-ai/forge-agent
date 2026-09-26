"""End-to-end order processing pipeline: build -> tag -> price -> fulfill."""
from orders import build_order
from tagging import tag_order
from pricing import apply_tag_discounts, compute_total
from inventory import reserve_stock
from shipping import estimate_shipping


def process_order(order_id, raw_items):
    order = build_order(order_id, raw_items)
    tag_order(order)
    apply_tag_discounts(order)
    reserve_stock(order)
    total = compute_total(order)
    shipping_cost = estimate_shipping(order)
    return {
        "order_id": order.order_id,
        "total": total,
        "shipping": shipping_cost,
        "tags": list(order.tags),
    }


def process_batch(batch):
    return [process_order(o["order_id"], o["items"]) for o in batch]
