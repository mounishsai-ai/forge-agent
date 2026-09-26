def remove_stock(inventory, name, amount):
    """
    Remove `amount` units of the item named `name` from the inventory.
    Raises ValueError if there isn't enough stock. Lookup should be
    case- and whitespace-insensitive, same as add_item.
    """
    item = inventory.items[name]
    if amount > item.quantity:
        raise ValueError(f"Not enough stock for {item.name!r}")
    item.quantity -= amount
    return item.quantity


def total_value(inventory):
    """Total dollar value of everything currently in stock."""
    return round(sum(item.price * item.quantity for item in inventory.items.values()), 2)


def restock_low_items(inventory, threshold, restock_amount):
    """Add restock_amount units to every item whose quantity is below threshold."""
    for item in inventory.items.values():
        if item.quantity < threshold:
            item.quantity += restock_amount
