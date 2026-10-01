from helpers import fl
from network import build_network, flight_from_row


def test_nodes_wait_arcs_and_mct():
    a = fl("MIA", "CLT", "07:00", "09:00", 100)
    b = fl("CLT", "ORD", "10:00", "11:00", 100)
    net = build_network([a, b], mct_min=45)
    assert [n.name for n in net.nodes] == ["CLT_0945", "CLT_1000"]
    assert net.tail[a.id] is None and net.head[a.id].name == "CLT_0945"
    assert net.tail[b.id].name == "CLT_1000" and net.head[b.id] is None
    assert [(u.name, v.name) for u, v in net.waits] == [("CLT_0945", "CLT_1000")]


def test_direct_flight_has_no_nodes():
    d = fl("MIA", "ORD", "08:00", "10:00", 150)
    net = build_network([d])
    assert net.nodes == [] and net.tail[d.id] is None and net.head[d.id] is None


def test_flights_into_origin_or_out_of_destination_are_ignored():
    net = build_network([fl("CLT", "MIA", "07:00", "09:00", 50), fl("ORD", "CLT", "07:00", "10:00", 50)])
    assert net.flights == []


def test_node_after_midnight_gets_day_suffix():
    late = fl("MIA", "CLT", "22:30", "23:50", 80)
    net = build_network([late], mct_min=45)
    assert net.head[late.id].name == "CLT_0035_d21"


def test_flight_from_snapshot_row():
    row = {"origin": "MIA", "dest": "ORD", "carrier": "AA", "airline": "American", "flight_number": "AA 1204",
           "dep_local": "2026-11-20T05:17:00-05:00", "arr_local": "2026-11-20T08:00:00-06:00",
           "price_usd": "227", "is_american": "True", "aircraft": "Boeing 737", "scraped_at": "x"}
    f = flight_from_row(row)
    assert f.id == "AA1204_MIAORD_0517" and f.price == 227 and f.is_american is True
    assert (f.arr - f.dep).total_seconds() == 223 * 60
