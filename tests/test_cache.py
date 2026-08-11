from mcp_garmin_connect.cache import TTLCache


def test_ttl_cache_reuses_value() -> None:
    cache = TTLCache(ttl_seconds=60)
    calls = 0

    def factory() -> int:
        nonlocal calls
        calls += 1
        return calls

    assert cache.get_or_set("x", factory) == 1
    assert cache.get_or_set("x", factory) == 1
    assert calls == 1


def test_ttl_cache_clear() -> None:
    cache = TTLCache(ttl_seconds=60)
    cache.get_or_set("x", lambda: 1)
    cache.clear()
    assert cache.get_or_set("x", lambda: 2) == 2
