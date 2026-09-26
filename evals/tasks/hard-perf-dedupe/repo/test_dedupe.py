from dedupe import find_near_duplicates


def test_basic_grouping():
    records = [
        {"id": 1, "title": "Wireless Mouse"},
        {"id": 2, "title": "wireless   mouse!!"},
        {"id": 3, "title": "USB Cable"},
        {"id": 4, "title": "usb-cable"},
        {"id": 5, "title": "Keyboard"},
    ]
    assert find_near_duplicates(records) == [[1, 2], [3, 4], [5]]


def test_order_independence_of_input():
    records = [
        {"id": 10, "title": "Blue Widget"},
        {"id": 3, "title": "Red Gadget"},
        {"id": 7, "title": "blue widget"},
        {"id": 1, "title": "red-gadget!"},
    ]
    assert find_near_duplicates(records) == [[1, 3], [7, 10]]


def test_all_unique():
    records = [{"id": i, "title": f"item-{i}"} for i in range(5)]
    result = find_near_duplicates(records)
    assert result == [[0], [1], [2], [3], [4]]
