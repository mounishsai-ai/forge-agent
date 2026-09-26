def average_score(records):
    """
    Return the average of the "score" field across a list of record
    dicts, e.g. [{"name": "a", "score": 10}, {"name": "b", "score": 20}].
    """
    total = 0
    for r in records:
        total += r["score"]
    return total / len(records)
