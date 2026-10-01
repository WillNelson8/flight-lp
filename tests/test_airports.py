from zoneinfo import ZoneInfo

from airports import AIRPORTS, DEST, HUBS, ORIGIN, search_routes


def test_22_airports_with_valid_time_zones():
    assert len(HUBS) == 20
    assert set(AIRPORTS) == set(HUBS) | {ORIGIN, DEST}
    for a in AIRPORTS.values():
        ZoneInfo(a.tz)


def test_421_routes_never_into_origin_or_out_of_destination():
    routes = search_routes()
    assert len(routes) == 421
    assert len(set(routes)) == 421
    assert all(o != d for o, d in routes)
    assert not any(d == ORIGIN or o == DEST for o, d in routes)
    assert (ORIGIN, DEST) in routes
