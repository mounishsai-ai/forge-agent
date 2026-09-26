"""Builds Order objects from raw incoming order data (e.g. from the checkout API)."""
from models import LineItem, Order


def build_order(order_id, raw_items, promo_tags=[]):
    """Create an Order from raw item dicts, tagging it with any active promo tags."""
    items = [LineItem(i["sku"], i["quantity"], i["unit_price"]) for i in raw_items]
    order = Order(order_id, items, tags=promo_tags)
    return order
