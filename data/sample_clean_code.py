def add_item(item, cache=None):
    if cache is None:
        cache = []
    cache.append(item)
    return cache


def read_file(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def classify(value):
    if value:
        return "yes"
    return "no"
