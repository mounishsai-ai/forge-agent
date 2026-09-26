from paginate import paginate


def test_first_page_has_full_size():
    items = list(range(10))
    assert paginate(items, 1, 3) == [0, 1, 2]
