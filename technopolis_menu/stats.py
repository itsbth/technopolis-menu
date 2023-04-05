STATS = {}


def incr_stat(key: str):
    STATS[key] = STATS.get(key, 0) + 1


def set_stat(key: str, value: int):
    STATS[key] = value


def get_all():
    return STATS
