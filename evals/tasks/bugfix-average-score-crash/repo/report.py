import json
import sys

from scores import average_score


def main():
    if len(sys.argv) != 2:
        print("Usage: python report.py <records.json>")
        sys.exit(2)
    path = sys.argv[1]
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    print(f"Average score: {average_score(records):.2f}")


if __name__ == "__main__":
    main()
