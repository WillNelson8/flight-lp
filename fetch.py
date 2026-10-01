"""Scrape real Nov 20 nonstop prices from Google Flights for every route in the network.

Usage:
    python fetch.py          start a new run, or resume the latest unfinished one
    python fetch.py --new    force a new run
"""
import json
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from selectolax.lexbor import LexborHTMLParser

from airports import AIRPORTS, TRIP_DATE

TRIP_DAY = tuple(int(p) for p in TRIP_DATE.split("-"))


def parse_time(value) -> tuple[int, int]:
    """Google omits zero components: [8] is 08:00 and [None, 31] is 00:31."""
    padded = [*(value or []), None, None]
    return (padded[0] or 0, padded[1] or 0)


def parse_payload(html: str) -> list[dict] | None:
    """Itineraries from both of Google's result lists, or None if the page carries no payload."""
    node = LexborHTMLParser(html).css_first(r"script.ds\:1")
    if node is None or "data:" not in node.text():
        return None
    data = node.text().split("data:", 1)[1].rsplit(",", 1)[0]
    if data.endswith("errorHasStatus: true"):
        return []
    try:
        payload = json.loads(data)
    except json.JSONDecodeError:
        return None
    itineraries = []
    for section in (payload[2], payload[3]):  # Google's "best" and "other" lists
        if not section or not section[0]:
            continue
        for item in section[0]:
            legs = []
            for leg in item[0][2]:
                code = leg[22] or [None, None, None, None]
                legs.append({
                    "origin": leg[3], "dest": leg[6],
                    "carrier": code[0], "number": code[1], "airline": code[3],
                    "dep_date": tuple(leg[20]), "dep_time": parse_time(leg[8]),
                    "arr_date": tuple(leg[21]), "arr_time": parse_time(leg[10]),
                    "aircraft": leg[17],
                })
            price = item[1][0][1] if item[1] and item[1][0] else None
            itineraries.append({"price": price, "legs": legs})
    return itineraries


def _local(airport: str, date: tuple, hm: tuple) -> datetime:
    return datetime(*date, *hm, tzinfo=ZoneInfo(AIRPORTS[airport].tz))


def nonstop_rows(itineraries: list[dict], origin: str, dest: str, scraped_at: str) -> tuple[list[dict], Counter]:
    """Validated snapshot rows for one searched route, plus drop counts by reason."""
    rows, drops, seen = [], Counter(), set()
    for it in itineraries:
        if len(it["legs"]) != 1:
            drops["not_nonstop"] += 1
            continue
        leg = it["legs"][0]
        if (leg["origin"], leg["dest"]) != (origin, dest):
            drops["route_mismatch"] += 1
            continue
        if not it["price"] or it["price"] <= 0:
            drops["missing_price"] += 1
            continue
        if leg["dep_date"] != TRIP_DAY:
            drops["wrong_date"] += 1
            continue
        dep = _local(origin, leg["dep_date"], leg["dep_time"])
        arr = _local(dest, leg["arr_date"], leg["arr_time"])
        if arr <= dep:
            drops["arrival_not_after_departure"] += 1
            continue
        flight_number = f"{leg['carrier']} {leg['number']}"
        if (flight_number, dep) in seen:
            drops["duplicate"] += 1
            continue
        seen.add((flight_number, dep))
        rows.append({
            "origin": origin, "dest": dest, "carrier": leg["carrier"], "airline": leg["airline"],
            "flight_number": flight_number, "dep_local": dep.isoformat(), "arr_local": arr.isoformat(),
            "price_usd": it["price"], "is_american": leg["carrier"] == "AA", "aircraft": leg["aircraft"],
            "scraped_at": scraped_at,
        })
    return rows, drops


def cheapest_itinerary(itineraries: list[dict]) -> dict | None:
    """Google's cheapest single-ticket itinerary; ties go to the earlier final arrival."""
    priced = [it for it in itineraries if it["price"]]
    if not priced:
        return None

    def arrival_key(it):
        leg = it["legs"][-1]
        return (*leg["arr_date"], *leg["arr_time"])

    best = min(priced, key=lambda it: (it["price"], arrival_key(it)))
    return {
        "price": best["price"],
        "legs": [{
            "origin": l["origin"], "dest": l["dest"],
            "flight_number": f"{l['carrier']} {l['number']}", "airline": l["airline"],
            "dep_local": "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}".format(*l["dep_date"], *l["dep_time"]),
            "arr_local": "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}".format(*l["arr_date"], *l["arr_time"]),
        } for l in best["legs"]],
    }
