from wordfreq import count_words, format_results


def test_count_words():
    counts = count_words("the Fox the fox THE")
    assert counts["the"] == 3
    assert counts["fox"] == 2


def test_default_sort_order():
    counts = count_words("b b a a c")
    # a and b tie at 2; alphabetical tiebreak puts a before b.
    assert format_results(counts) == "a\t2\nb\t2\nc\t1"
