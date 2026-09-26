import argparse
import re
from collections import Counter


def count_words(text):
    words = re.findall(r"[a-zA-Z']+", text.lower())
    return Counter(words)


def format_results(counts):
    lines = []
    for word, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"{word}\t{count}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Count word frequency in a text file.")
    parser.add_argument("file", help="path to text file")
    args = parser.parse_args()

    with open(args.file, encoding="utf-8") as f:
        text = f.read()

    counts = count_words(text)
    print(format_results(counts))


if __name__ == "__main__":
    main()
