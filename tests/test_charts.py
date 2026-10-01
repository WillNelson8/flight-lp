import charts
from helpers import fl
from model import Itinerary


def test_rank_styles_darkest_first_and_dotted_past_five():
    assert charts.rank_color(1) == charts.RANK_TONES[0]
    assert charts.rank_color(7) == charts.RANK_TONES[-1]
    assert charts.rank_dash(5) == "solid" and charts.rank_dash(6) == "dot"
    assert charts.rank_width(1) > charts.rank_width(2) > charts.rank_width(5)


def test_route_map_separates_itineraries_on_the_same_airport_pair():
    a = fl("MIA", "ORD", "08:00", "10:00", 227)
    b = fl("MIA", "ORD", "09:00", "11:00", 227)
    fig = charts.route_map([a, b], [Itinerary(1, [a], "LP"), Itinerary(2, [b], "IP with cuts")])
    mids = {}
    for t in fig.data:
        if t.name in ("rank 1", "rank 2"):
            mids[t.name] = (t.lat[len(t.lat) // 2], t.lon[len(t.lon) // 2])
    assert mids["rank 1"] != mids["rank 2"]


def test_time_space_draws_the_wait_at_the_connection():
    a = fl("MIA", "CLT", "07:00", "09:00", 100)
    b = fl("CLT", "ORD", "10:00", "11:00", 100)
    fig = charts.time_space([a, b], [Itinerary(1, [a, b], "LP")])
    path = next(t for t in fig.data if t.name == "rank 1")
    ys = [y for y in path.y if y is not None]
    assert ys == ["MIA", "CLT", "CLT", "ORD"]  # the CLT -> CLT segment is the wait


def test_cost_bars_label_missing_itinerary():
    fig = charts.cost_bars([("S1", 227), ("S2", None)])
    assert any("no feasible itinerary" in (a.text or "") for a in fig.layout.annotations)


def test_heatmap_marks_failed_and_blank_routes():
    a = fl("MIA", "CLT", "07:00", "09:00", 100)
    fig = charts.price_heatmap([a], {("MIA", "CLT"): "ok", ("MIA", "ATL"): "failed", ("MIA", "DFW"): "no_service"})
    hm = fig.data[0]
    row = list(hm.y).index("MIA")
    col = {c: i for i, c in enumerate(hm.x)}
    assert hm.z[row][col["CLT"]] == 100
    assert hm.z[row][col["DFW"]] is None
    assert hm.text[row][col["ATL"]] == "x"
