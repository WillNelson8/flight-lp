"""The LP: cheapest same-day MIA to ORD itinerary on the time-space network, plus K-best via no-good cuts.

Usage:
    python model.py [--k 5] [--mct 45] [--partial]
"""
import tempfile
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import networkx as nx
import pulp

from airports import DEST, ORIGIN
from network import Flight, Network

CT = ZoneInfo("America/Chicago")
DEADLINE = datetime(2026, 11, 20, 23, 59, tzinfo=CT)
DAY_START = datetime(2026, 11, 20, 0, 0, tzinfo=CT)
TIE_PER_FLIGHT = 0.00003
TIE_ARRIVAL_WEIGHT = 0.5  # dollars spread across the 1440-minute day
GROUP_LABEL = {"C4": "sameday", "C5": "airline", "C6": "onestop"}


@dataclass(frozen=True)
class Scenario:
    key: str
    label: str
    american_only: bool
    one_stop: bool


SCENARIOS = [
    Scenario("S1", "American, any stops", True, False),
    Scenario("S2", "American, one stop at most", True, True),
    Scenario("S3", "All airlines, any stops", False, False),
    Scenario("S4", "All airlines, one stop at most", False, True),
]
SCENARIO_BY_KEY = {s.key: s for s in SCENARIOS}


def tie_term(f: Flight) -> float:
    """Far below $1: orders equal-price itineraries by earlier ORD arrival, then fewer flights."""
    term = TIE_PER_FLIGHT
    if f.dest == DEST:
        minutes = (f.arr - DAY_START).total_seconds() / 60
        term += TIE_ARRIVAL_WEIGHT * minutes / 1440
    return term


def excluded_reason(f: Flight, scenario: Scenario) -> str | None:
    """The first rule that fixes x_f = 0 in this scenario: C4 same day, C5 airline, C6 one stop."""
    if f.dest == DEST and f.arr > DEADLINE:
        return "C4"
    if scenario.american_only and not f.is_american:
        return "C5"
    if scenario.one_stop and f.origin != ORIGIN and f.dest != DEST:
        return "C6"
    return None


@dataclass
class Itinerary:
    rank: int
    flights: list[Flight]
    method: str  # "LP" or "IP with cuts"

    @property
    def cost(self) -> int:
        return sum(f.price for f in self.flights)

    @property
    def stops(self) -> int:
        return len(self.flights) - 1

    @property
    def airports(self) -> list[str]:
        return [self.flights[0].origin] + [f.dest for f in self.flights]

    @property
    def dep(self) -> datetime:
        return self.flights[0].dep

    @property
    def arr(self) -> datetime:
        return self.flights[-1].arr


@dataclass
class ConstraintRow:
    name: str
    group: str
    expression: str
    lhs: float


@dataclass
class SolveResult:
    scenario: Scenario
    mct: int
    status: str
    itineraries: list[Itinerary]
    n_variables: int
    n_constraints: int
    n_flights_allowed: int
    integral: bool | None
    lp_objective: float | None
    duals: dict[str, float] = field(default_factory=dict)
    reduced_costs: dict[str, float] = field(default_factory=dict)
    constraints: list[ConstraintRow] = field(default_factory=list)
    lp_text: str = ""
    shortest_path_cost: float | None = None
    node_labels: dict[str, float] = field(default_factory=dict)
    reach_cost: dict[str, int] = field(default_factory=dict)
    price_drop: dict[str, float | None] = field(default_factory=dict)  # unchosen flight -> exact drop to enter; None = no trip uses it


def build_problem(net: Network, scenario: Scenario, binary: bool = False, cuts=()):
    # C7: x, w >= 0. The upper bound 1 is implied by C1 to C3 (one unit of flow), so the LP leaves it
    # off; that keeps every chosen variable basic, which makes the duals readable as cost-to-reach labels.
    cat = pulp.LpBinary if binary else pulp.LpContinuous
    prob = pulp.LpProblem(f"MIA_ORD_{scenario.key}", pulp.LpMinimize)
    x = {f.id: prob.add_variable(f"x_{f.id}", lowBound=0, cat=cat) for f in net.flights}
    w = {(a.name, b.name): prob.add_variable(f"w_{a.name}__{b.name}", lowBound=0, cat=cat) for a, b in net.waits}

    prob += pulp.lpSum((f.price + tie_term(f)) * x[f.id] for f in net.flights), "total_cost"
    prob += pulp.lpSum(x[f.id] for f in net.flights if net.tail[f.id] is None) == 1, "C1_start_MIA"
    prob += pulp.lpSum(x[f.id] for f in net.flights if net.head[f.id] is None) == 1, "C2_end_ORD"

    inflow = {n: [] for n in net.nodes}
    outflow = {n: [] for n in net.nodes}
    for f in net.flights:
        if net.head[f.id] is not None:
            inflow[net.head[f.id]].append(x[f.id])
        if net.tail[f.id] is not None:
            outflow[net.tail[f.id]].append(x[f.id])
    for a, b in net.waits:
        outflow[a].append(w[(a.name, b.name)])
        inflow[b].append(w[(a.name, b.name)])
    for n in net.nodes:
        prob += pulp.lpSum(inflow[n]) - pulp.lpSum(outflow[n]) == 0, f"C3_bal_{n.name}"

    for f in net.flights:
        reason = excluded_reason(f, scenario)
        if reason:
            prob += x[f.id] == 0, f"{reason}_{GROUP_LABEL[reason]}_{f.id}"
    for i, path in enumerate(cuts, 1):
        prob += pulp.lpSum(x[f.id] for f in path) <= len(path) - 1, f"CUT{i}"
    return prob, x, w


def _solve(prob: pulp.LpProblem) -> str:
    # PuLP 3.3 bundles CBC only as PULP_CBC_CMD, which it marks deprecated ahead of PuLP 4.0.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="PULP_CBC_CMD is deprecated", category=DeprecationWarning)
        prob.solve(pulp.PULP_CBC_CMD(msg=False))
    return pulp.LpStatus[prob.status]


def _chosen(net: Network, x) -> list[Flight]:
    return sorted((f for f in net.flights if (x[f.id].value() or 0) > 0.5), key=lambda f: f.dep)


def _lp_text(prob: pulp.LpProblem) -> str:
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "model.lp"
        prob.writeLP(str(path))
        return path.read_text()


def _constraint_rows(prob: pulp.LpProblem) -> list[ConstraintRow]:
    rows = []
    for c in prob.constraints():
        group = "CUT" if c.name.startswith("CUT") else c.name.split("_")[0]
        lhs = sum(coef * (var.value() or 0) for var, coef in c.items())
        rows.append(ConstraintRow(c.name, group, str(c).replace("= -0.0", "= 0").replace("= 0.0", "= 0"), lhs))
    return rows


def _graph(net: Network, scenario: Scenario) -> nx.DiGraph:
    g = nx.DiGraph()
    for f in net.flights:
        if excluded_reason(f, scenario):
            continue
        u = net.tail[f.id].name if net.tail[f.id] else ORIGIN
        v = net.head[f.id].name if net.head[f.id] else DEST
        weight = f.price + tie_term(f)
        if not g.has_edge(u, v) or g[u][v]["weight"] > weight:
            g.add_edge(u, v, weight=weight)
    for a, b in net.waits:
        g.add_edge(a.name, b.name, weight=0.0)
    return g


def _shortest_paths(net: Network, scenario: Scenario) -> tuple[float | None, dict[str, float], dict[str, int]]:
    g = _graph(net, scenario)
    if ORIGIN not in g:
        return None, {}, {}
    labels = nx.single_source_dijkstra_path_length(g, ORIGIN, weight="weight")
    reach = {}
    for n in net.nodes:
        if n.name in labels:
            cost = int(labels[n.name])  # tie term is below $1, so int() recovers whole dollars
            reach[n.airport] = min(reach.get(n.airport, cost), cost)
    return labels.get(DEST), labels, reach


def _price_drop(net: Network, scenario: Scenario, forward: dict[str, float], optimum: float,
                chosen_ids: set[str]) -> dict[str, float | None]:
    """Exact sensitivity: cheapest full trip through each unchosen flight minus the optimum.

    The LP is degenerate, so simplex reduced costs are often 0 for flights that cannot reach ORD at all;
    forward labels (MIA to tail) plus backward labels (head to ORD) give the true amount.
    """
    backward = nx.single_source_dijkstra_path_length(_graph(net, scenario).reverse(copy=False), DEST, weight="weight")
    drops = {}
    for f in net.flights:
        if f.id in chosen_ids or excluded_reason(f, scenario):
            continue
        u = net.tail[f.id].name if net.tail[f.id] else ORIGIN
        v = net.head[f.id].name if net.head[f.id] else DEST
        if u not in forward or v not in backward:
            drops[f.id] = None
        else:
            drops[f.id] = forward[u] + f.price + tie_term(f) + backward[v] - optimum
    return drops


def solve(net: Network, scenario: Scenario, k: int = 5) -> SolveResult:
    prob, x, w = build_problem(net, scenario)
    status = _solve(prob)
    sp_cost, labels, reach = _shortest_paths(net, scenario)
    allowed = [f for f in net.flights if excluded_reason(f, scenario) is None]
    base = dict(scenario=scenario, mct=net.mct, n_variables=len(prob.variables()), n_constraints=len(prob.constraints()),
                n_flights_allowed=len(allowed), lp_text=_lp_text(prob), shortest_path_cost=sp_cost,
                node_labels=labels, reach_cost=reach)
    if status != "Optimal":
        return SolveResult(status="infeasible", itineraries=[], integral=None, lp_objective=None,
                           constraints=_constraint_rows(prob), **base)

    integral = all(abs((v.value() or 0) - round(v.value() or 0)) < 1e-6 for v in prob.variables())
    first = Itinerary(1, _chosen(net, x), "LP")
    chosen_ids = {f.id for f in first.flights}
    result = SolveResult(
        status="optimal", itineraries=[first], integral=integral, lp_objective=pulp.value(prob.objective),
        duals={c.name: c.pi for c in prob.constraints()},
        reduced_costs={f.id: x[f.id].dj for f in allowed if f.id not in chosen_ids},
        constraints=_constraint_rows(prob), **base,
    )
    result.price_drop = _price_drop(net, scenario, labels, result.lp_objective, chosen_ids)
    for rank in range(2, k + 1):
        cuts = [it.flights for it in result.itineraries]
        ip, x2, _ = build_problem(net, scenario, binary=True, cuts=cuts)
        if _solve(ip) != "Optimal":
            break
        result.itineraries.append(Itinerary(rank, _chosen(net, x2), "IP with cuts"))
    for i, it in enumerate(result.itineraries[:-1], 1):
        expr = " + ".join(f"x_{f.id}" for f in it.flights) + f" <= {len(it.flights) - 1}"
        result.constraints.append(ConstraintRow(f"CUT{i}", "CUT", expr, float(len(it.flights))))
    return result


def dual_labels(result: SolveResult) -> dict[str, float]:
    """Cost-to-reach implied by the LP duals: pi_C1 + pi_node. Equals the shortest-path label on the optimal path."""
    start = result.duals.get("C1_start_MIA", 0.0)
    return {name.removeprefix("C3_bal_"): start + pi for name, pi in result.duals.items() if name.startswith("C3_bal_")}


def load_flights(run_dir: Path) -> list[Flight]:
    import snapshot
    from network import flight_from_row
    return [flight_from_row(r) for r in snapshot.read_rows(run_dir / "flights.csv")]


def main() -> None:
    import argparse
    import snapshot
    from network import build_network

    parser = argparse.ArgumentParser(description="Solve all four scenarios on the latest scrape and print a report.")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--mct", type=int, default=45)
    parser.add_argument("--partial", action="store_true", help="allow an unfinished run (for development)")
    args = parser.parse_args()
    run_dir = snapshot.latest_run() or (snapshot.latest_run(complete=False) if args.partial else None)
    if run_dir is None:
        raise SystemExit("No complete scrape found. Run `python fetch.py` first (or pass --partial).")
    net = build_network(load_flights(run_dir), args.mct)
    out = Path(__file__).parent / "out"
    out.mkdir(exist_ok=True)
    print(f"Run {run_dir.name}: {len(net.flights)} flights, {len(net.nodes)} nodes, {len(net.waits)} wait arcs, MCT {args.mct} min")
    for s in SCENARIOS:
        r = solve(net, s, args.k)
        (out / f"{s.key}.lp").write_text(r.lp_text)
        print(f"\n{s.key} {s.label}: {r.n_variables} variables, {r.n_constraints} constraints")
        if r.status != "optimal":
            print("  No feasible itinerary")
            continue
        check = "match" if abs(r.lp_objective - r.shortest_path_cost) < 1e-6 else "MISMATCH"
        print(f"  integrality check: {'pass' if r.integral else 'FAIL'}; networkx cross-check: {check}")
        for it in r.itineraries:
            legs = ", ".join(f"{f.flight_number} {f.origin}-{f.dest} {f.dep:%H:%M}-{f.arr:%H:%M} ${f.price}" for f in it.flights)
            print(f"  #{it.rank} ${it.cost} ({it.method}): {legs}")


if __name__ == "__main__":
    main()
