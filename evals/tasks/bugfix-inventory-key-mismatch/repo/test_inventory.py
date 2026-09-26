from inventory.models import Inventory
from inventory.operations import remove_stock, total_value


def test_add_and_total_value():
    inv = Inventory()
    inv.add_item("Widget", 2.5, 10)
    assert total_value(inv) == 25.0


def test_remove_stock_case_insensitive():
    inv = Inventory()
    inv.add_item("Widget", 2.5, 10)
    remove_stock(inv, "widget", 3)
    assert inv.get("widget").quantity == 7
