"""Data classes for the order-processing pipeline."""


class LineItem:
    def __init__(self, sku, quantity, unit_price):
        self.sku = sku
        self.quantity = quantity
        self.unit_price = unit_price

    @property
    def subtotal(self):
        return round(self.quantity * self.unit_price, 2)


class Order:
    def __init__(self, order_id, items, tags=None):
        self.order_id = order_id
        self.items = items
        self.tags = tags if tags is not None else []
        self.discount_percent = 0
