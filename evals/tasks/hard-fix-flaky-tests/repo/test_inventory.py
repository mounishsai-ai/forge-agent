"""CI has been randomly failing on this file -- not every run, just
sometimes, and not always the same test. Nobody's been able to pin it down
because it reproduces inconsistently."""
import time

from inventory import Item, tag_summary, save_items, load_items, DATA_FILE


def test_tag_summary_order():
    items = [Item("widget", {"blue", "small", "cheap"}), Item("gadget", {"red", "small"})]
    result = tag_summary(items)
    assert list(result) == ["small", "blue", "red", "cheap"]


def test_item_is_fresh():
    item = Item("widget", {"blue"})
    time.sleep(0.05)
    assert item.age_seconds() < 0.1


def test_save_then_load():
    items = [Item("widget", {"blue"}), Item("gadget", {"red"})]
    save_items(items, DATA_FILE)
    loaded = load_items(DATA_FILE)
    assert {i.name for i in loaded} == {"widget", "gadget"}


def test_load_missing_file_is_empty():
    assert load_items(DATA_FILE) == []
