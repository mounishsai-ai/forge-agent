class Product:
    def __init__(self, sku, name, price):
        self.sku = sku
        self.name = name
        self.price = price  # price per unit, in dollars


class CartItem:
    def __init__(self, product, quantity):
        self.product = product
        self.quantity = quantity

    @property
    def subtotal(self):
        return round(self.product.price * self.quantity, 2)


class Cart:
    def __init__(self):
        self.items = []  # list of CartItem
        self.discount_code = None  # str or None; at most one code active

    def add(self, product, quantity=1):
        for item in self.items:
            if item.product.sku == product.sku:
                item.quantity += quantity
                return item
        item = CartItem(product, quantity)
        self.items.append(item)
        return item

    def subtotal(self):
        return round(sum(item.subtotal for item in self.items), 2)

    def apply_code(self, code):
        """Attach a discount code to the cart, replacing any previous one."""
        self.discount_code = code

    def clear_code(self):
        self.discount_code = None
