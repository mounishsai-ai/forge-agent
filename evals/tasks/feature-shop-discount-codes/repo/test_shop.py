from shop.models import Product, Cart
from shop.pricing import calculate_total


def test_subtotal_multiple_items():
    cart = Cart()
    cart.add(Product("sku1", "Widget", 10.0), quantity=2)
    cart.add(Product("sku2", "Gadget", 5.0), quantity=3)
    assert cart.subtotal() == 35.0


def test_total_without_discount_code():
    cart = Cart()
    cart.add(Product("sku1", "Widget", 10.0), quantity=2)
    assert calculate_total(cart, registry={}) == 20.0
