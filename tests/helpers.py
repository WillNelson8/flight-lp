import itertools
from datetime import datetime
from zoneinfo import ZoneInfo

from airports import AIRPORTS
from network import Flight, flight_id

_numbers = itertools.count(1000)


def fl(origin, dest, dep, arr, price, carrier="AA", arr_day=20) -> Flight:
    """A toy flight on 2026-11-20. dep and arr are local 'HH:MM' at the origin and destination."""
    dh, dm = map(int, dep.split(":"))
    ah, am = map(int, arr.split(":"))
    d = datetime(2026, 11, 20, dh, dm, tzinfo=ZoneInfo(AIRPORTS[origin].tz))
    a = datetime(2026, 11, arr_day, ah, am, tzinfo=ZoneInfo(AIRPORTS[dest].tz))
    number = f"{carrier} {next(_numbers)}"
    return Flight(id=flight_id(number, origin, dest, d), origin=origin, dest=dest, carrier=carrier,
                  airline={"AA": "American", "UA": "United", "F9": "Frontier"}.get(carrier, carrier),
                  flight_number=number, dep=d, arr=a, price=price, is_american=carrier == "AA")
