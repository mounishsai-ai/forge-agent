"""Find near-duplicate records by title.

Two records are considered near-duplicates if their titles are the same
after normalize_title() (case-insensitive, ignoring anything that isn't a
letter or digit - so punctuation, spacing and casing differences don't
matter).

find_near_duplicates(records) returns a list of groups, where:
  - each group is a sorted list of the "id" values of the records that are
    near-duplicates of each other,
  - singleton records (no duplicates) still form their own one-element
    group,
  - the groups are sorted by their smallest id, ascending.

Example: given records with (id, title) pairs
    (1, "Wireless Mouse"), (2, "wireless   mouse!!"), (3, "USB Cable")
this returns [[1, 2], [3]].
"""
import difflib
import re


def normalize_title(title):
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def find_near_duplicates(records, threshold=0.92):
    groups = []  # list of lists of indices into `records`
    for i, rec in enumerate(records):
        norm_i = normalize_title(rec["title"])
        placed = False
        for group in groups:
            rep_idx = group[0]
            norm_rep = normalize_title(records[rep_idx]["title"])
            ratio = difflib.SequenceMatcher(None, norm_i, norm_rep).ratio()
            if ratio >= threshold:
                group.append(i)
                placed = True
                break
        if not placed:
            groups.append([i])

    result = [sorted(records[idx]["id"] for idx in group) for group in groups]
    result.sort(key=lambda g: g[0])
    return result
