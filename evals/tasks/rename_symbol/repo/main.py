from core import calc_total
from orders import order_summary, order_summary_via_module
from report import generate_report, report_grand_total

SAMPLE_ORDERS = [
    {"id": 1, "items": [{"price": 10.0, "qty": 2}, {"price": 5.0, "qty": 1}]},
    {"id": 2, "items": [{"price": 3.5, "qty": 4}]},
]


def main():
    for order in SAMPLE_ORDERS:
        print(order_summary(order))
        print(order_summary_via_module(order))
    print(generate_report(SAMPLE_ORDERS))
    print(report_grand_total(SAMPLE_ORDERS))
    # calc_total can also be used directly on an ad-hoc list of items.
    print(calc_total([{"price": 1.0, "qty": 1}]))


if __name__ == "__main__":
    main()
