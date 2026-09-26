import os
import subprocess
import sys


def main():
    cwd = os.getcwd()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_shop.py", "-q"],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print("Visible test test_shop.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)

    sys.path.insert(0, cwd)
    for mod in ("shop.models", "shop.discounts", "shop.pricing", "shop"):
        sys.modules.pop(mod, None)
    from shop.models import Product, Cart
    from shop.discounts import DiscountCode
    from shop.pricing import calculate_total

    def new_cart(price, qty):
        cart = Cart()
        cart.add(Product("sku1", "Widget", price), quantity=qty)
        return cart

    registry = {
        "SAVE10": DiscountCode("SAVE10", "percent", 10, min_spend=0),
        "FLAT5": DiscountCode("FLAT5", "fixed", 5.0, min_spend=20),
        "BIGSPENDER": DiscountCode("BIGSPENDER", "percent", 50, min_spend=1000),
        "HUGEFIXED": DiscountCode("HUGEFIXED", "fixed", 500.0, min_spend=0),
    }

    # No discount code: total == subtotal.
    cart = new_cart(10.0, 2)  # subtotal 20.0
    assert calculate_total(cart, registry) == 20.0

    # Percent discount, no min_spend requirement.
    cart = new_cart(10.0, 2)  # subtotal 20.0
    cart.apply_code("SAVE10")
    assert calculate_total(cart, registry) == 18.0, calculate_total(cart, registry)

    # Fixed discount, min_spend met exactly.
    cart = new_cart(10.0, 2)  # subtotal 20.0
    cart.apply_code("FLAT5")
    assert calculate_total(cart, registry) == 15.0

    # Fixed discount, min_spend NOT met -> code ignored, no error.
    cart = new_cart(10.0, 1)  # subtotal 10.0 < 20 min_spend
    cart.apply_code("FLAT5")
    assert calculate_total(cart, registry) == 10.0

    # Percent discount, min_spend far from met.
    cart = new_cart(10.0, 2)  # subtotal 20.0 << 1000
    cart.apply_code("BIGSPENDER")
    assert calculate_total(cart, registry) == 20.0

    # Unknown code raises ValueError.
    cart = new_cart(10.0, 1)
    cart.apply_code("NOPE")
    try:
        calculate_total(cart, registry)
        assert False, "expected ValueError for unknown code"
    except ValueError:
        pass

    # Case-insensitive / whitespace-insensitive lookup.
    cart = new_cart(10.0, 2)  # subtotal 20.0
    cart.apply_code("  save10 ")
    assert calculate_total(cart, registry) == 18.0

    # Fixed discount larger than subtotal clamps at 0, never negative.
    cart = new_cart(10.0, 1)  # subtotal 10.0
    cart.apply_code("HUGEFIXED")
    assert calculate_total(cart, registry) == 0.0

    # Replacing a code: applying a new code overrides the old one.
    cart = new_cart(10.0, 2)  # subtotal 20.0
    cart.apply_code("SAVE10")
    cart.apply_code("FLAT5")
    assert calculate_total(cart, registry) == 15.0, "second apply_code should replace the first"

    # Clearing the code falls back to plain subtotal.
    cart = new_cart(10.0, 2)
    cart.apply_code("SAVE10")
    cart.clear_code()
    assert calculate_total(cart, registry) == 20.0

    print("OK")


if __name__ == "__main__":
    main()
