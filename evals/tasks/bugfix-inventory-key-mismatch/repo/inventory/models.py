class Item:
    def __init__(self, name, price, quantity=0):
        self.name = name
        self.price = price
        self.quantity = quantity

    def __repr__(self):
        return f"Item({self.name!r}, price={self.price}, quantity={self.quantity})"


class Inventory:
    """
    Items are keyed internally by a normalized version of their name
    (stripped of surrounding whitespace, lowercased) so that lookups are
    case- and whitespace-insensitive, while Item.name keeps the original
    display text of whichever add_item call first created the entry.
    """

    def __init__(self):
        self.items = {}  # normalized name -> Item

    @staticmethod
    def normalize(name):
        return name.strip().lower()

    def add_item(self, name, price, quantity=0):
        key = self.normalize(name)
        if key in self.items:
            self.items[key].quantity += quantity
        else:
            self.items[key] = Item(name, price, quantity)
        return self.items[key]

    def get(self, name):
        return self.items[self.normalize(name)]
