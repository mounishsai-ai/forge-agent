from slugify import slugify


def test_basic():
    assert slugify("Hello, World!") == "hello-world"


def test_repeated_separators():
    assert slugify("a---b__c") == "a-b-c"


def test_unicode():
    assert slugify("café naïve") == "cafe-naive"


def test_empty():
    assert slugify("") == ""
