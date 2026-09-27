def paginate(items, page, per_page):
    """Return one page from items; page numbers start at one."""
    if type(page) is not int or type(per_page) is not int:
        raise ValueError("page and per_page must be positive integers")
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page must be positive integers")
    start = page * per_page
    return list(items[start:start + per_page])

