import pytest

from helpers import fl
from model import SCENARIO_BY_KEY, dual_labels, solve
from network import build_network

S1, S2, S3, S4 = (SCENARIO_BY_KEY[k] for k in ("S1", "S2", "S3", "S4"))


def best(flights, scenario=S3, mct=45, k=1):
    result = solve(build_network(flights, mct), scenario, k)
    if result.status == "optimal":
        assert result.integral is True
        assert result.lp_objective == pytest.approx(result.shortest_path_cost, abs=1e-6)  # LP == networkx
    return result


def test_direct_flight_is_cheapest():
    r = best([fl("MIA", "ORD", "08:00", "10:00", 150), fl("MIA", "CLT", "07:00", "09:00", 100), fl("CLT", "ORD", "10:00", "11:00", 100)])
    assert r.itineraries[0].cost == 150 and r.itineraries[0].airports == ["MIA", "ORD"]


def test_connection_cheaper_than_direct():
    r = best([fl("MIA", "ORD", "08:00", "10:00", 300), fl("MIA", "CLT", "07:00", "09:00", 100), fl("CLT", "ORD", "10:00", "11:00", 100)])
    assert r.itineraries[0].cost == 200 and r.itineraries[0].airports == ["MIA", "CLT", "ORD"]


def test_connection_tighter_than_mct_is_not_used():
    flights = [fl("MIA", "ORD", "08:00", "10:00", 300), fl("MIA", "CLT", "07:00", "09:00", 50), fl("CLT", "ORD", "09:30", "10:30", 50)]
    assert best(flights, mct=45).itineraries[0].cost == 300
    assert best(flights, mct=30).itineraries[0].cost == 100


def test_connection_in_central_time_uses_local_clock():
    # Lands BNA 09:00 CT; the onward flight leaves 09:30 CT, only 30 minutes later.
    flights = [fl("MIA", "ORD", "08:00", "10:00", 300), fl("MIA", "BNA", "08:00", "09:00", 50), fl("BNA", "ORD", "09:30", "11:00", 50)]
    assert best(flights).itineraries[0].cost == 300


def test_same_day_deadline_boundary():
    on_time = [fl("MIA", "ORD", "08:00", "10:00", 300), fl("MIA", "CLT", "18:00", "20:00", 50), fl("CLT", "ORD", "23:00", "23:59", 50)]
    assert best(on_time).itineraries[0].cost == 100  # lands exactly 23:59 CT: allowed
    late = [fl("MIA", "ORD", "08:00", "10:00", 300), fl("MIA", "CLT", "18:00", "20:00", 50), fl("CLT", "ORD", "23:00", "00:05", 50, arr_day=21)]
    r = best(late)
    assert r.itineraries[0].cost == 300
    assert any(c.group == "C4" for c in r.constraints)


def test_american_filter():
    flights = [fl("MIA", "ORD", "08:00", "10:00", 100, carrier="UA"), fl("MIA", "ORD", "09:00", "11:00", 200)]
    assert best(flights, S3).itineraries[0].cost == 100
    assert best(flights, S1).itineraries[0].flights[0].carrier == "AA"


def test_one_stop_rule_blocks_two_stop_route():
    flights = [
        fl("MIA", "CLT", "06:00", "08:00", 50), fl("CLT", "BNA", "09:00", "09:30", 50), fl("BNA", "ORD", "10:30", "12:00", 50),
        fl("MIA", "ATL", "06:00", "08:00", 125), fl("ATL", "ORD", "09:00", "10:00", 125),
        fl("MIA", "ORD", "08:00", "10:00", 400),
    ]
    assert best(flights, S3).itineraries[0].stops == 2
    four = best(flights, S4)
    assert four.itineraries[0].cost == 250 and four.itineraries[0].airports == ["MIA", "ATL", "ORD"]


def test_infeasible_scenario_returns_status_not_exception():
    r = solve(build_network([fl("MIA", "CLT", "07:00", "09:00", 100)]), S3, 3)
    assert r.status == "infeasible" and r.itineraries == []


def test_k_best_order_and_ties_by_arrival():
    flights = [
        fl("MIA", "ORD", "08:00", "10:00", 300),
        fl("MIA", "CLT", "06:00", "08:00", 100), fl("CLT", "ORD", "09:00", "10:00", 100),
        fl("CLT", "ORD", "12:00", "13:00", 100),
        fl("MIA", "ATL", "06:00", "08:00", 125), fl("ATL", "ORD", "09:00", "10:00", 125),
    ]
    r = solve(build_network(flights), S3, k=5)
    assert [it.cost for it in r.itineraries] == [200, 200, 250, 300]  # only 4 exist
    assert r.itineraries[0].arr < r.itineraries[1].arr  # tie broken by earlier ORD arrival
    assert [it.method for it in r.itineraries] == ["LP", "IP with cuts", "IP with cuts", "IP with cuts"]
    assert sum(1 for c in r.constraints if c.group == "CUT") == 3


def test_strong_duality_and_dual_labels_on_optimal_path():
    flights = [fl("MIA", "ORD", "08:00", "10:00", 300), fl("MIA", "CLT", "07:00", "09:00", 100), fl("CLT", "ORD", "10:00", "11:00", 100)]
    r = best(flights)
    # CBC reports duals rounded to about 5 decimal places, so compare at 1e-4.
    assert r.duals["C1_start_MIA"] + r.duals["C2_end_ORD"] == pytest.approx(r.lp_objective, abs=1e-4)
    labels = dual_labels(r)
    assert labels["CLT_0945"] == pytest.approx(r.node_labels["CLT_0945"], abs=1e-4)
    assert r.reach_cost["CLT"] == 100


def test_lp_text_and_sizes():
    r = best([fl("MIA", "ORD", "08:00", "10:00", 150), fl("MIA", "CLT", "07:00", "09:00", 100), fl("CLT", "ORD", "10:00", "11:00", 100)])
    assert "C1_start_MIA" in r.lp_text and "C2_end_ORD" in r.lp_text
    assert r.n_variables == 4  # 3 flights + 1 wait arc
    assert {c.group for c in r.constraints} == {"C1", "C2", "C3"}


def test_price_drop_needed_is_exact_where_lp_reduced_costs_are_degenerate():
    direct = fl("MIA", "ORD", "08:00", "10:00", 300)
    a = fl("MIA", "CLT", "07:00", "09:00", 100)
    b = fl("CLT", "ORD", "10:00", "11:00", 100)
    dead_end = fl("MIA", "ATL", "07:00", "09:00", 20)  # nothing leaves ATL, so it can never be on a trip
    r = best([direct, a, b, dead_end])
    assert r.price_drop[direct.id] == pytest.approx(100, abs=1)
    assert r.price_drop[dead_end.id] is None
    assert a.id not in r.price_drop and b.id not in r.price_drop  # chosen flights are not listed


def test_constraint_expressions_print_zero_not_negative_zero():
    r = best([fl("MIA", "CLT", "07:00", "09:00", 100), fl("CLT", "ORD", "10:00", "11:00", 100)])
    assert not any("-0.0" in c.expression for c in r.constraints)
