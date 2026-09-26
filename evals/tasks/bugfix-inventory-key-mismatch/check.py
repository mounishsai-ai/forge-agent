import os
import subprocess
import sys


def main():
    cwd = os.getcwd()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_inventory.py", "-q"],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print("Visible test test_inventory.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)

    sys.path.insert(0, cwd)
    for mod in ("inventory.models", "inventory.operations", "inventory"):
        sys.modules.pop(mod, None)
    from inventory.models import Inventory
    from inventory.operations import remove_stock, total_value, restock_low_items

    # Case/whitespace-insensitive remove after case/whitespace-insensitive add.
    inv = Inventory()
    inv.add_item("Widget", 2.5, 10)
    remove_stock(inv, "  WIDGET  ", 4)
    assert inv.get("widget").quantity == 6, "case/whitespace-insensitive remove failed"

    # Merging quantities on repeated add with different casing.
    inv2 = Inventory()
    inv2.add_item("Gadget", 5.0, 2)
    inv2.add_item("gadget", 5.0, 3)
    assert len(inv2.items) == 1, "different-case adds should merge into one item"
    assert inv2.get("GADGET").quantity == 5

    # Not enough stock raises ValueError, and doesn't corrupt state.
    inv3 = Inventory()
    inv3.add_item("Bolt", 0.1, 5)
    try:
        remove_stock(inv3, "bolt", 10)
        assert False, "expected ValueError for insufficient stock"
    except ValueError:
        pass
    assert inv3.get("bolt").quantity == 5, "failed removal should not change quantity"

    # total_value across multiple items.
    inv4 = Inventory()
    inv4.add_item("A", 2.0, 3)
    inv4.add_item("B", 1.5, 4)
    assert total_value(inv4) == 12.0, f"total_value wrong: {total_value(inv4)}"

    # restock_low_items increments items below threshold, and remove_stock
    # afterwards still works with normalized keys.
    inv5 = Inventory()
    inv5.add_item("Low One", 1.0, 1)
    inv5.add_item("High One", 1.0, 50)
    restock_low_items(inv5, threshold=5, restock_amount=10)
    assert inv5.get("Low One").quantity == 11
    assert inv5.get("High One").quantity == 50
    remove_stock(inv5, "low one", 1)
    assert inv5.get("low one").quantity == 10

    # Original display name is preserved from the first add_item call.
    inv6 = Inventory()
    inv6.add_item("Display Name", 1.0, 1)
    inv6.add_item("display name", 1.0, 1)
    assert inv6.get("DISPLAY NAME").name == "Display Name"

    print("OK")


if __name__ == "__main__":
    main()
