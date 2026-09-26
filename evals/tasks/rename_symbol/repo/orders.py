import core
from core import calc_total


def order_summary(order):
    """Return a dict describing an order's line-item total."""
    return {"id": order["id"], "total": calc_total(order["items"])}


def order_summary_via_module(order):
    """Same as order_summary but calls calc_total through the module (core.calc_total)."""
    return {"id": order["id"], "total": core.calc_total(order["items"])}
