from pathlib import Path

import fetch
import snapshot

FIX = Path(__file__).parent / "fixtures"
PAGES = {name: (FIX / f"{name}.html").read_text() for name in ("mia_ord_nonstop", "cvg_ord_nonstop", "sav_mem_nonstop", "mia_ord_any")}


def route_of(query):
    fd = query.flight_data[0]
    return fd.from_airport.airport, fd.to_airport.airport, fd.HasField("max_stops")


def good_fetch(query):
    o, d, nonstop = route_of(query)
    if not nonstop:
        return PAGES["mia_ord_any"]
    return {("MIA", "ORD"): PAGES["mia_ord_nonstop"], ("CVG", "ORD"): PAGES["cvg_ord_nonstop"]}.get((o, d), PAGES["sav_mem_nonstop"])


def test_full_run_completes(tmp_path):
    run_dir = snapshot.new_run_dir("2026-10-01_1500", tmp_path)
    assert fetch.run(run_dir, fetch_html=good_fetch, sleep=lambda s: None, log=lambda m: None) is True
    status = snapshot.route_status(run_dir)
    assert len(status) == 421
    assert status[("MIA", "ORD")] == "ok" and status[("CVG", "ORD")] == "ok" and status[("SAV", "MEM")] == "no_service"
    assert len(snapshot.read_rows(run_dir / "flights.csv")) == 13 + 14
    assert snapshot.is_complete(run_dir)
    assert snapshot.latest_run(tmp_path) == run_dir


def test_stops_after_five_consecutive_failures_and_resumes_without_duplicates(tmp_path):
    run_dir = snapshot.new_run_dir("2026-10-01_1500", tmp_path)
    calls = {"n": 0}

    def flaky(query):
        calls["n"] += 1
        if calls["n"] > 12:
            return "<html>unusual traffic</html>"  # block page: no payload
        return good_fetch(query)

    assert fetch.run(run_dir, fetch_html=flaky, sleep=lambda s: None, log=lambda m: None) is False
    status = snapshot.route_status(run_dir)
    assert list(status.values()).count("failed") == 5
    assert not snapshot.is_complete(run_dir)
    assert snapshot.latest_run(tmp_path, complete=False) == run_dir

    assert fetch.run(run_dir, fetch_html=good_fetch, sleep=lambda s: None, log=lambda m: None) is True
    assert len(snapshot.read_rows(run_dir / "flights.csv")) == 13 + 14
    assert set(snapshot.route_status(run_dir).values()) <= {"ok", "no_service"}


def test_exceptions_count_as_failures(tmp_path):
    run_dir = snapshot.new_run_dir("2026-10-01_1500", tmp_path)

    def boom(query):
        raise ConnectionError("network down")

    assert fetch.run(run_dir, fetch_html=boom, sleep=lambda s: None, log=lambda m: None) is False
    assert not (run_dir / "reference.json").exists()
