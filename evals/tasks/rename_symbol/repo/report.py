from core import calc_total


def generate_report(orders):
    """Build a report mapping order id -> total, using calc_total for each order."""
    return {order["id"]: calc_total(order["items"]) for order in orders}


def report_grand_total(orders):
    """Sum calc_total across every order."""
    return sum(calc_total(order["items"]) for order in orders)
