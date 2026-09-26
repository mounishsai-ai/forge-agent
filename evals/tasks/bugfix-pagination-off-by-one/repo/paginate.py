def paginate(items, page, page_size):
    """
    Return the items for a 1-indexed page number.

    - page 1 returns the first page_size items, page 2 the next
      page_size items, and so on.
    - If page is beyond the available data, returns an empty list.
    - page and page_size are positive integers.
    """
    if page < 1 or page_size < 1:
        return []
    start = (page - 1) * page_size
    end = start + page_size - 1
    return items[start:end]
