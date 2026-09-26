"""Sales report generator.

This module is a classic "god class": ReportGenerator does CSV loading,
input validation, three different aggregations, AND two different render
formats (CSV summary, HTML page), all as methods on one object. It works
fine, but it's a maintenance headache -- e.g. you can't unit-test the
aggregation math without also going through file I/O, and you can't add a
third render format without wading through 400 lines of unrelated loading
code.

Public API (must keep working exactly as before): generate_report(path, fmt)
where fmt is "csv" or "html".
"""
from __future__ import annotations

import csv


class ReportGenerator:
    """Loads sales records from a CSV file and renders a summary report.

    Input CSV columns (with header row): date,category,product,quantity,unit_price
      - date: "YYYY-MM-DD"
      - category, product: arbitrary non-empty strings
      - quantity: positive integer
      - unit_price: non-negative decimal number

    Rows with quantity <= 0 raise ValueError (mentioning the row number,
    1-indexed counting the header as row 1). Rows with a non-numeric
    quantity or unit_price also raise ValueError. Blank lines are skipped.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self.records: list[dict] = []

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load(self) -> None:
        """Read self.path and populate self.records with validated,
        type-coerced rows (quantity: int, unit_price: float, line_total:
        float = quantity * unit_price)."""
        with open(self.path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row_num = 1  # header is row 1
            for raw in reader:
                row_num += 1
                if raw is None or all((v is None or v.strip() == "") for v in raw.values()):
                    continue
                self.records.append(self._parse_row(raw, row_num))

    def _parse_row(self, raw: dict, row_num: int) -> dict:
        date = (raw.get("date") or "").strip()
        category = (raw.get("category") or "").strip()
        product = (raw.get("product") or "").strip()
        quantity_str = (raw.get("quantity") or "").strip()
        price_str = (raw.get("unit_price") or "").strip()

        if not date or not category or not product:
            raise ValueError(f"row {row_num}: missing required field(s)")

        try:
            quantity = int(quantity_str)
        except ValueError:
            raise ValueError(f"row {row_num}: quantity {quantity_str!r} is not an integer")

        if quantity <= 0:
            raise ValueError(f"row {row_num}: quantity must be positive, got {quantity}")

        try:
            unit_price = float(price_str)
        except ValueError:
            raise ValueError(f"row {row_num}: unit_price {price_str!r} is not a number")

        if unit_price < 0:
            raise ValueError(f"row {row_num}: unit_price must not be negative, got {unit_price}")

        line_total = quantity * unit_price
        return {
            "date": date,
            "category": category,
            "product": product,
            "quantity": quantity,
            "unit_price": unit_price,
            "line_total": line_total,
        }

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------
    def category_totals(self) -> dict:
        """Return {category: {"quantity": int, "revenue": float}}."""
        totals: dict = {}
        for r in self.records:
            bucket = totals.setdefault(r["category"], {"quantity": 0, "revenue": 0.0})
            bucket["quantity"] += r["quantity"]
            bucket["revenue"] += r["line_total"]
        return totals

    def month_totals(self) -> dict:
        """Return {"YYYY-MM": {"quantity": int, "revenue": float}}."""
        totals: dict = {}
        for r in self.records:
            month = r["date"][:7]
            bucket = totals.setdefault(month, {"quantity": 0, "revenue": 0.0})
            bucket["quantity"] += r["quantity"]
            bucket["revenue"] += r["line_total"]
        return totals

    def day_totals(self) -> dict:
        """Return {"YYYY-MM-DD": {"quantity": int, "revenue": float}}."""
        totals: dict = {}
        for r in self.records:
            day = r["date"]
            bucket = totals.setdefault(day, {"quantity": 0, "revenue": 0.0})
            bucket["quantity"] += r["quantity"]
            bucket["revenue"] += r["line_total"]
        return totals

    def top_products(self, n: int = 3) -> list:
        """Return up to n (product, revenue) tuples, highest revenue first;
        ties broken by product name ascending."""
        totals: dict = {}
        for r in self.records:
            totals[r["product"]] = totals.get(r["product"], 0.0) + r["line_total"]
        ordered = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))
        return ordered[:n]

    def overall_total(self) -> dict:
        """Return {"quantity": int, "revenue": float, "count": int}."""
        quantity = sum(r["quantity"] for r in self.records)
        revenue = sum(r["line_total"] for r in self.records)
        return {"quantity": quantity, "revenue": revenue, "count": len(self.records)}

    # ------------------------------------------------------------------
    # Rendering: CSV
    # ------------------------------------------------------------------
    def render_csv(self) -> str:
        lines = ["Section,Key,Quantity,Revenue"]

        for category in sorted(self.category_totals()):
            bucket = self.category_totals()[category]
            lines.append(f"Category,{category},{bucket['quantity']},{bucket['revenue']:.2f}")

        for month in sorted(self.month_totals()):
            bucket = self.month_totals()[month]
            lines.append(f"Month,{month},{bucket['quantity']},{bucket['revenue']:.2f}")

        for day in sorted(self.day_totals()):
            bucket = self.day_totals()[day]
            lines.append(f"Day,{day},{bucket['quantity']},{bucket['revenue']:.2f}")

        for product, revenue in self.top_products():
            lines.append(f"TopProduct,{product},,{revenue:.2f}")

        overall = self.overall_total()
        lines.append(f"Total,,{overall['quantity']},{overall['revenue']:.2f}")

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # Rendering: HTML
    # ------------------------------------------------------------------
    def render_html(self) -> str:
        parts = ["<html>", "<head><title>Sales Report</title></head>", "<body>", "<h1>Sales Report</h1>"]

        parts.append("<h2>By Category</h2>")
        parts.append("<table>")
        parts.append("<tr><th>Category</th><th>Quantity</th><th>Revenue</th></tr>")
        for category in sorted(self.category_totals()):
            bucket = self.category_totals()[category]
            parts.append(
                f"<tr><td>{category}</td><td>{bucket['quantity']}</td>"
                f"<td>{bucket['revenue']:.2f}</td></tr>"
            )
        parts.append("</table>")

        parts.append("<h2>By Month</h2>")
        parts.append("<table>")
        parts.append("<tr><th>Month</th><th>Quantity</th><th>Revenue</th></tr>")
        for month in sorted(self.month_totals()):
            bucket = self.month_totals()[month]
            parts.append(
                f"<tr><td>{month}</td><td>{bucket['quantity']}</td>"
                f"<td>{bucket['revenue']:.2f}</td></tr>"
            )
        parts.append("</table>")

        parts.append("<h2>By Day</h2>")
        parts.append("<table>")
        parts.append("<tr><th>Day</th><th>Quantity</th><th>Revenue</th></tr>")
        for day in sorted(self.day_totals()):
            bucket = self.day_totals()[day]
            parts.append(
                f"<tr><td>{day}</td><td>{bucket['quantity']}</td>"
                f"<td>{bucket['revenue']:.2f}</td></tr>"
            )
        parts.append("</table>")

        parts.append("<h2>Top Products</h2>")
        parts.append("<table>")
        parts.append("<tr><th>Product</th><th>Revenue</th></tr>")
        for product, revenue in self.top_products():
            parts.append(f"<tr><td>{product}</td><td>{revenue:.2f}</td></tr>")
        parts.append("</table>")

        overall = self.overall_total()
        parts.append(
            f"<p>Total: {overall['count']} orders, {overall['quantity']} items, "
            f"${overall['revenue']:.2f}</p>"
        )
        parts.append("</body>")
        parts.append("</html>")

        return "\n".join(parts) + "\n"

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def generate(self, fmt: str) -> str:
        if fmt == "csv":
            return self.render_csv()
        if fmt == "html":
            return self.render_html()
        raise ValueError(f"unknown report format: {fmt!r}")


def generate_report(path: str, fmt: str) -> str:
    """Public entry point: load `path`, render it as `fmt` ("csv" or
    "html"), and return the rendered report as a string."""
    gen = ReportGenerator(path)
    gen.load()
    return gen.generate(fmt)
