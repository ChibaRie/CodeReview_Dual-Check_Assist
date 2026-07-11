# BUG: mutable default argument
def add_item(item, cache=[]):
    cache.append(item)
    return cache

# BUG: bare except
def read_file(path):
    try:
        f = open(path)
        return f.read()
    except:
        return ""

# BUG: deep nesting + is literal
def classify(value):
    if value is True:
        if value is not None:
            if value != False:
                if value == 1:
                    return "yes"
    return "no"

# BUG: TODO marker
# TODO: refactor this before release
