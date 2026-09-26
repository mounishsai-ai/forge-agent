"""Tiny driver: python main.py [cart.json]  -> prints the cart's total."""
import json
import sys

from cart import total


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "cart.json"
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    grand_total = total(data["items"], data.get("code"))
    print(f"Total: ${grand_total:.2f}")


if __name__ == "__main__":
    main()
