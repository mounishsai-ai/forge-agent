"""Generic string helpers used across the app."""


def slugify(text):
    return "-".join(text.lower().split())


def truncate(text, length=80):
    return text if len(text) <= length else text[: length - 3] + "..."
