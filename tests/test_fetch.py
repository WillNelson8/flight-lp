from datetime import datetime
from pathlib import Path

import fetch

FIX = Path(__file__).parent / "fixtures"


def html(name):
    return (FIX / name).read_text()


def test_parse_time_expands_omitted_components():
    assert fetch.parse_time([8]) == (8, 0)
    assert fetch.parse_time([None, 31]) == (0, 31)
    assert fetch.parse_time([14, 5]) == (14, 5)
    assert fetch.parse_time(None) == (0, 0)


def test_parse_reads_both_best_and_other_lists():
    its = fetch.parse_payload(html("mia_ord_nonstop.html"))
    numbers = {f"{it['legs'][0]['carrier']} {it['legs'][0]['number']}" for it in its}
    assert len(its) == 13
    assert "AA 3174" in numbers  # from Google's "best" list, which fast-flights' own parser drops
    assert "AA 1204" in numbers  # from the "other" list
    assert all(it["price"] == 227 for it in its)


def test_blocked_page_returns_none():
    assert fetch.parse_payload("<html><body>Our systems have detected unusual traffic</body></html>") is None


def test_no_service_route_returns_empty_list():
    assert fetch.parse_payload(html("sav_mem_nonstop.html")) == []


def test_nonstop_rows_local_times_and_durations():
    rows, drops = fetch.nonstop_rows(fetch.parse_payload(html("mia_ord_nonstop.html")), "MIA", "ORD", "2026-10-01T19:00:00+00:00")
    assert len(rows) == 13 and sum(drops.values()) == 0
    r = next(r for r in rows if r["flight_number"] == "AA 1204")
    assert r["dep_local"] == "2026-11-20T05:17:00-05:00"
    assert r["arr_local"] == "2026-11-20T08:00:00-06:00"
    dep, arr = datetime.fromisoformat(r["dep_local"]), datetime.fromisoformat(r["arr_local"])
    assert (arr - dep).total_seconds() / 60 == 223  # Google's reported duration
    assert r["is_american"] is True and r["carrier"] == "AA" and r["price_usd"] == 227


def test_after_midnight_arrival_keeps_next_day_date():
    rows, _ = fetch.nonstop_rows(fetch.parse_payload(html("mia_ord_nonstop.html")), "MIA", "ORD", "x")
    late = next(r for r in rows if r["dep_local"].startswith("2026-11-20T22:07"))
    assert late["arr_local"] == "2026-11-21T00:47:00-06:00"


def test_american_eagle_counts_as_american():
    rows, _ = fetch.nonstop_rows(fetch.parse_payload(html("cvg_ord_nonstop.html")), "CVG", "ORD", "x")
    by_num = {r["flight_number"]: r for r in rows}
    assert len(rows) == 14
    assert by_num["AA 4097"]["is_american"] is True  # Embraer 170, American Eagle
    assert by_num["UA 5521"]["is_american"] is False


def test_duplicates_and_bad_rows_are_dropped_and_counted():
    its = fetch.parse_payload(html("cvg_ord_nonstop.html"))
    bad_price = {**its[1], "price": None}
    rows, drops = fetch.nonstop_rows([its[0], its[0], bad_price, its[2]], "CVG", "ORD", "x")
    assert len(rows) == 2  # its[0] once plus its[2]
    assert drops["duplicate"] == 1 and drops["missing_price"] == 1
    rows, drops = fetch.nonstop_rows([its[0]], "MIA", "ORD", "x")
    assert rows == [] and drops["route_mismatch"] == 1


def test_reference_is_cheapest_single_ticket():
    ref = fetch.cheapest_itinerary(fetch.parse_payload(html("mia_ord_any.html")))
    assert ref["price"] == 163
    assert [(l["origin"], l["dest"]) for l in ref["legs"]] == [("MIA", "ATL"), ("ATL", "ORD")]
    assert ref["legs"][0]["flight_number"].startswith("F9 ")
