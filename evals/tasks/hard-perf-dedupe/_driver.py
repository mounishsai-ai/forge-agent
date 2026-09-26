"""Hidden driver, invoked by check.py in a subprocess with a hard timeout.

Not part of the repo the agent sees. Loads records from a JSON file, calls
the repo's dedupe.find_near_duplicates on them, writes the result to
another JSON file.

Usage: python _driver.py <records_json_path> <output_json_path>
"""
import json
import os
import sys


def main():
    records_path, output_path = sys.argv[1], sys.argv[2]
    with open(records_path, "r", encoding="utf-8") as f:
        records = json.load(f)

    sys.path.insert(0, os.getcwd())
    from dedupe import find_near_duplicates

    result = find_near_duplicates(records)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f)


if __name__ == "__main__":
    main()
