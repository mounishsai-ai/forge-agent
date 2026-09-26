from pipeline import process_order, process_batch


def _small_items():
    # Fewer than 3 items - never triggers the "bulk" tag.
    return [
        {"sku": "A1", "quantity": 2, "unit_price": 10.0},
        {"sku": "B2", "quantity": 1, "unit_price": 5.0},
    ]


def test_single_small_order():
    result = process_order("ORD-1", _small_items())
    assert result["total"] == 25.0
    assert result["tags"] == []


def test_small_batch():
    batch = [
        {"order_id": f"ORD-{i}", "items": _small_items()}
        for i in range(5)
    ]
    results = process_batch(batch)
    assert len(results) == 5
    for r in results:
        assert r["total"] == 25.0
        assert r["tags"] == []
