"""Scrape real Nov 20 nonstop prices from Google Flights for every route in the network.

Usage:
    python fetch.py          start a new run, or resume the latest unfinished one
    python fetch.py --new    force a new run
"""
import argparse
import json
import random
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from selectolax.lexbor import LexborHTMLParser

import snapshot
from airports import AIRPORTS, DEST, ORIGIN, TRIP_DATE, search_routes

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


def build_query(origin: str, dest: str, max_stops: int | None, airlines: list[str] | None = None,
                single_ticket: bool = False):
    from fast_flights import FlightQuery, Passengers, create_query
    return create_query(
        flights=[FlightQuery(date=TRIP_DATE, from_airport=origin, to_airport=dest,
                             max_stops=max_stops, airlines=airlines)],
        seat="economy", trip="one-way", passengers=Passengers(adults=1),
        language="en-US", currency="USD", hide_separate_and_self_transfer=single_ticket,
    )


def google_fetch(query) -> str:
    from fast_flights import fetch_flights_html
    return fetch_flights_html(query)


def _attempt(fetch_html, query, label, log) -> list[dict] | None:
    try:
        itineraries = parse_payload(fetch_html(query))
    except Exception as exc:  # network errors count as failures, like block pages
        log(f"{label}: error {exc!r}")
        return None
    if itineraries is None:
        log(f"{label}: no result payload (blocked or CAPTCHA page)")
    return itineraries


def run(run_dir: Path, fetch_html=google_fetch, sleep=time.sleep, pause=(2.0, 4.0), max_failures=5, log=print) -> bool:
    """Scrape everything not yet done in run_dir. Returns True once the run is complete."""
    failures = 0
    ref_path = run_dir / "reference.json"
    if not ref_path.exists():
        reference = {}
        for key, airlines in (("all", None), ("american", ["AA"])):
            its = _attempt(fetch_html, build_query(ORIGIN, DEST, None, airlines, single_ticket=True), f"reference {key}", log)
            sleep(random.uniform(*pause))
            if its is None:
                failures += 1
                break
            reference[key] = cheapest_itinerary(its)
        else:
            ref_path.write_text(json.dumps(reference, indent=2))

    status = snapshot.route_status(run_dir)
    todo = [r for r in search_routes() if status.get(r) not in ("ok", "no_service")]
    for i, (o, d) in enumerate(todo, 1):
        if failures >= max_failures:
            break
        scraped_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        its = _attempt(fetch_html, build_query(o, d, 0), f"{o}-{d}", log)
        if its is None:
            failures += 1
            snapshot.append_rows(run_dir / "routes.csv", snapshot.ROUTE_COLUMNS,
                                 [{"origin": o, "dest": d, "status": "failed", "n_flights": 0, "scraped_at": scraped_at}])
        else:
            failures = 0
            rows, drops = nonstop_rows(its, o, d, scraped_at)
            snapshot.append_rows(run_dir / "flights.csv", snapshot.FLIGHT_COLUMNS, rows)
            snapshot.append_rows(run_dir / "drops.csv", snapshot.DROP_COLUMNS,
                                 [{"origin": o, "dest": d, "reason": r, "count": c} for r, c in drops.items()])
            state = "ok" if rows else "no_service"
            snapshot.append_rows(run_dir / "routes.csv", snapshot.ROUTE_COLUMNS,
                                 [{"origin": o, "dest": d, "status": state, "n_flights": len(rows), "scraped_at": scraped_at}])
            log(f"[{i}/{len(todo)}] {o}-{d}: {state} ({len(rows)} flights)")
        sleep(random.uniform(*pause))

    status = snapshot.route_status(run_dir)
    remaining = [r for r in search_routes() if status.get(r) not in ("ok", "no_service")]
    if failures >= max_failures:
        log(f"Stopped after {failures} consecutive failures. Progress is saved; run `python fetch.py` later to resume.")
    if remaining or not ref_path.exists():
        log(f"{len(remaining)} routes still to do. Run `python fetch.py` again to resume.")
        return False
    snapshot.mark_complete(run_dir)
    log(f"Run complete: {run_dir}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--new", action="store_true", help="start a new run even if one is unfinished")
    args = parser.parse_args()
    run_dir = None if args.new else snapshot.latest_run(complete=False)
    if run_dir is None:
        run_dir = snapshot.new_run_dir(datetime.now().strftime("%Y-%m-%d_%H%M"))
        print(f"New run: {run_dir}", flush=True)
    else:
        print(f"Resuming: {run_dir}", flush=True)
    run(run_dir, log=lambda m: print(m, flush=True))


if __name__ == "__main__":
    main()
