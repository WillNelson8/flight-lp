"""MIA to ORD same-day LP dashboard.

Run:  streamlit run dashboard.py
"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

import charts
import snapshot
from airports import AIRPORTS, DEST, ORIGIN, search_routes
from model import SCENARIO_BY_KEY, SCENARIOS, dual_labels, solve
from network import build_network, flight_from_row

ET = ZoneInfo("America/New_York")
SCENARIO_KEY = {(True, False): "S1", (True, True): "S2", (False, False): "S3", (False, True): "S4"}
OTHER_AIRLINE = {"S1": "S3", "S2": "S4", "S3": "S1", "S4": "S2"}
PLOT_CONFIG = {"displayModeBar": False, "scrollZoom": False}

st.set_page_config(page_title="MIA to ORD LP", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
html, body, .stApp, .stMarkdown, button, input, textarea, select { font-family: 'Inter', -apple-system, 'Segoe UI', sans-serif; }
.block-container { padding-top: 2rem; max-width: 1400px; }
h1 { font-weight: 650; letter-spacing: -0.01em; }
[data-testid="stDataFrame"], .tile, .num { font-variant-numeric: tabular-nums; }
.lede { color: #41536B; font-size: 15px; margin-top: -6px; }
.dataline { color: #64748B; font-size: 13px; margin: 2px 0 18px; font-variant-numeric: tabular-nums; }
.tile { background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 14px 16px; min-height: 172px; }
.tile.best { border: 1.5px solid #2563EB; }
.tile .label { color: #41536B; font-size: 12px; font-weight: 600; letter-spacing: 0.03em; text-transform: uppercase; }
.tile .price { color: #0E1B2E; font-size: 30px; font-weight: 650; margin: 4px 0 2px; }
.tile .route { color: #0E1B2E; font-size: 14px; font-weight: 500; }
.tile .meta { color: #64748B; font-size: 12.5px; margin-top: 2px; }
.tile .flag { color: #2563EB; font-size: 11.5px; font-weight: 600; letter-spacing: 0.02em; }
.tile .empty { color: #64748B; font-size: 14px; margin-top: 10px; }
.note { color: #41536B; font-size: 13.5px; line-height: 1.55; }
</style>
""", unsafe_allow_html=True)


# ---------- data ----------

def _pick_run():
    run = snapshot.latest_run()
    if run is not None:
        return run, False
    run = snapshot.latest_run(complete=False)
    return (run, True) if run is not None else (None, False)


def _mtime(run_dir) -> float:
    files = [run_dir / n for n in ("flights.csv", "routes.csv", "reference.json", "COMPLETE")]
    return max((f.stat().st_mtime for f in files if f.exists()), default=0.0)


@st.cache_data(show_spinner=False)
def load_run(run_name: str, mtime: float) -> dict:
    run_dir = snapshot.DATA_DIR / run_name
    rows = snapshot.read_rows(run_dir / "flights.csv")
    ref_path = run_dir / "reference.json"
    drops = {}
    for r in snapshot.read_rows(run_dir / "drops.csv"):
        drops[r["reason"]] = drops.get(r["reason"], 0) + int(r["count"])
    return {
        "flights": [flight_from_row(r) for r in rows],
        "rows": rows,
        "status": snapshot.route_status(run_dir),
        "reference": json.loads(ref_path.read_text()) if ref_path.exists() else {},
        "drops": drops,
    }


@st.cache_data(show_spinner="Solving the LP")
def solved(run_name: str, mtime: float, key: str, mct: int, k: int):
    data = load_run(run_name, mtime)
    return solve(build_network(data["flights"], mct), SCENARIO_BY_KEY[key], k)


@st.cache_data(show_spinner=False)
def network_size(run_name: str, mtime: float, mct: int) -> tuple[int, int, int]:
    net = build_network(load_run(run_name, mtime)["flights"], mct)
    return len(net.flights), len(net.nodes), len(net.waits)


# ---------- formatting ----------

def route_text(airports: list[str]) -> str:
    return " → ".join(airports)


def stops_text(n: int) -> str:
    return "Nonstop" if n == 0 else f"{n} stop" if n == 1 else f"{n} stops"


def duration_text(minutes: float) -> str:
    h, m = divmod(int(round(minutes)), 60)
    return f"{h}h {m:02d}m"


def itinerary_table(it) -> pd.DataFrame:
    rows, total = [], 0
    for i, f in enumerate(it.flights):
        total += f.price
        layover = ""
        if i + 1 < len(it.flights):
            layover = duration_text((it.flights[i + 1].dep - f.arr).total_seconds() / 60)
        rows.append({
            "Leg": i + 1, "Flight": f.flight_number, "Airline": f.airline, "From": f.origin,
            "Depart (local)": f"{f.dep:%H:%M}", "To": f.dest, "Arrive (local)": f"{f.arr:%H:%M}",
            "Layover after": layover, "Price": f"${f.price}", "Running total": f"${total}",
        })
    return pd.DataFrame(rows)


def tile(label: str, price: int | None, route: str, meta: str, best: bool, flag: str = "") -> str:
    if price is None:
        body = '<div class="empty">No feasible itinerary</div>'
    else:
        body = f'<div class="price">${price}</div><div class="route">{route}</div><div class="meta">{meta}</div>'
    flag_html = f'<div class="flag">{flag}</div>' if flag else ""
    return f'<div class="tile{" best" if best else ""}"><div class="label">{label}</div>{body}{flag_html}</div>'


# ---------- page ----------

run_dir, partial = _pick_run()
st.title("MIA to ORD, Friday Nov 20, 2026")
st.markdown('<div class="lede">The cheapest same-day trip from Miami to Chicago O\'Hare, solved as a linear program '
            'on a time-space network of real Google Flights prices.</div>', unsafe_allow_html=True)
if run_dir is None:
    st.info("No scrape found yet. Run `python fetch.py` to collect today's Nov 20 prices, then reload this page.")
    st.stop()

mtime = _mtime(run_dir)
data = load_run(run_dir.name, mtime)
status = data["status"]
n_ok = sum(1 for v in status.values() if v == "ok")
scraped = sorted(r["scraped_at"] for r in data["rows"])
if scraped:
    first = datetime.fromisoformat(scraped[0]).astimezone(ET)
    last = datetime.fromisoformat(scraped[-1]).astimezone(ET)
    when = f"scraped from Google Flights on {first:%b %-d, %Y} between {first:%-I:%M %p} and {last:%-I:%M %p} ET"
else:
    when = "no flights scraped yet"
st.markdown(f'<div class="dataline">{len(data["flights"])} nonstop flights on {n_ok} served routes '
            f'({len(status)} of {len(search_routes())} routes searched), {when}. Run {run_dir.name}.</div>',
            unsafe_allow_html=True)
if partial:
    st.warning(f"Partial scrape: {len(status)} of {len(search_routes())} routes searched so far. "
               "Results will change when `python fetch.py` finishes.")

c1, c2, c3, c4 = st.columns([1, 1, 1.4, 1.4])
airline = c1.segmented_control("Airline", ["American", "All airlines"], default="All airlines") or "All airlines"
stops = c2.segmented_control("Stops", ["Any", "One at most"], default="Any") or "Any"
mct = c3.slider("Minimum connection (minutes)", 30, 120, 45, step=15)
k = c4.slider("Itineraries to rank (K)", 1, 10, 5)
key = SCENARIO_KEY[(airline == "American", stops == "One at most")]
result = solved(run_dir.name, mtime, key, mct, k)
flights_by_id = {f.id: f for f in data["flights"]}

# Summary tiles
tops = {s.key: solved(run_dir.name, mtime, s.key, mct, 1) for s in SCENARIOS}
ref_all = (data["reference"] or {}).get("all")
ref_aa = (data["reference"] or {}).get("american")
prices = [r.itineraries[0].cost for r in tops.values() if r.itineraries] + ([ref_all["price"]] if ref_all else [])
cheapest = min(prices) if prices else None
cols = st.columns(5)
for col, s in zip(cols, SCENARIOS):
    r = tops[s.key]
    it = r.itineraries[0] if r.itineraries else None
    col.markdown(tile(
        s.label, it.cost if it else None, route_text(it.airports) if it else "",
        f"{stops_text(it.stops)}, departs {it.dep:%H:%M}, arrives {it.arr:%H:%M} local" if it else "",
        best=it is not None and it.cost == cheapest, flag="Selected" if s.key == key else "",
    ), unsafe_allow_html=True)
if ref_all:
    ref_route = [ref_all["legs"][0]["origin"]] + [l["dest"] for l in ref_all["legs"]]
    meta = f"{ref_all['legs'][0]['flight_number'].split()[0]}, {stops_text(len(ref_all['legs']) - 1)}"
    if ref_aa:
        meta += f". American single ticket: ${ref_aa['price']}"
    cols[4].markdown(tile("Google single ticket", ref_all["price"], route_text(ref_route), meta,
                          best=ref_all["price"] == cheapest), unsafe_allow_html=True)
else:
    cols[4].markdown(tile("Google single ticket", None, "", "", False), unsafe_allow_html=True)
st.write("")

tab_solution, tab_lp, tab_sens, tab_data = st.tabs(["Solution", "The linear program", "Sensitivity", "Data"])

with tab_solution:
    if result.status != "optimal":
        st.info(f"{result.scenario.label}: no feasible same-day itinerary with a {mct} minute minimum connection.")
    else:
        its = result.itineraries
        map_col, list_col = st.columns([2.2, 1])
        with list_col:
            st.subheader(f"Top {len(its)} by price")
            options = ["Show all"] + [f"#{it.rank}  ${it.cost}  {route_text(it.airports)}  {it.dep:%H:%M} to {it.arr:%H:%M}"
                                      for it in its]
            choice = st.radio("Highlight", options, index=0, label_visibility="collapsed")
            highlight = None if choice == "Show all" else options.index(choice)
            if len(its) < k:
                st.caption(f"Only {len(its)} same-day itineraries exist for this scenario.")
            st.caption("Ties in price are ordered by earlier arrival at ORD, then fewer flights. "
                       "Ranks 1 to 5 get darker blues; ranks past 5 are dotted.")
        overlay = list_col.toggle("Show the other airline filter's #1 (dashed)", value=True)
        compare = None
        if overlay:
            other = solved(run_dir.name, mtime, OTHER_AIRLINE[key], mct, 1)
            compare = other.itineraries[0] if other.itineraries else None
        allowed = [f for f in data["flights"] if f.dest != ORIGIN and f.origin != DEST]
        with map_col:
            st.plotly_chart(charts.route_map(allowed, its, highlight, compare), width="stretch",
                            config=PLOT_CONFIG)
            if compare is not None:
                st.caption(f"Dashed gray: #1 for {SCENARIO_BY_KEY[OTHER_AIRLINE[key]].label}, ${compare.cost}.")

        shown = its[(highlight or 1) - 1]
        st.subheader(f"Itinerary #{shown.rank}: ${shown.cost}, {stops_text(shown.stops).lower()}")
        st.dataframe(itinerary_table(shown), hide_index=True, width="stretch")

        st.subheader("Time-space diagram")
        st.caption("Every scraped flight is a gray line from departure to arrival. The ranked itineraries are drawn in blue; "
                   "a horizontal blue segment is time spent waiting at a connecting airport.")
        st.plotly_chart(charts.time_space(allowed, its, highlight), width="stretch", config=PLOT_CONFIG)

    st.subheader("Cheapest price by scenario")
    items = [(s.label, tops[s.key].itineraries[0].cost if tops[s.key].itineraries else None) for s in SCENARIOS]
    if ref_all:
        items.append(("Google single ticket, all airlines", ref_all["price"]))
    if ref_aa:
        items.append(("Google single ticket, American", ref_aa["price"]))
    st.plotly_chart(charts.cost_bars(items), width="stretch", config=PLOT_CONFIG)
    st.caption("Scenario prices add up separate one-way tickets for each leg. Google's single-ticket fare prices the "
               "whole trip as one booking, so the two can differ in either direction.")

with tab_lp:
    st.subheader("Formulation")
    st.markdown('<div class="note">Each flight f is a variable x<sub>f</sub> (1 if you take it). Each node is an airport at a '
                'specific time: a departure time, or an arrival time plus the minimum connection time. Wait arcs w<sub>g</sub> '
                'link consecutive nodes at the same airport at zero cost. Because every arc moves forward in time, the '
                'network has no cycles.</div>', unsafe_allow_html=True)
    st.latex(r"""
\begin{aligned}
\min\ & \sum_{f \in F} (p_f + \tau_f)\, x_f \\
\text{s.t.}\ & \textstyle\sum_{f \in \mathrm{Out}(\mathrm{MIA})} x_f = 1 && \text{C1 start} \\
& \textstyle\sum_{f \in \mathrm{In}(\mathrm{ORD})} x_f = 1 && \text{C2 end} \\
& \textstyle\sum_{a \in \mathrm{in}(n)} y_a - \sum_{a \in \mathrm{out}(n)} y_a = 0 \quad \forall n \in N && \text{C3 balance} \\
& x_f = 0 \quad \forall f \in \mathrm{In}(\mathrm{ORD}) : \mathrm{arr}_f > \text{23:59 CT} && \text{C4 same day} \\
& x_f = 0 \quad \forall f : \mathrm{carrier}_f \neq \mathrm{AA} \ \ (\text{American scenarios}) && \text{C5 airline} \\
& x_f = 0 \quad \forall f \notin \mathrm{Out}(\mathrm{MIA}) \cup \mathrm{In}(\mathrm{ORD}) \ \ (\text{one-stop scenarios}) && \text{C6 one stop} \\
& x_f \ge 0,\ \ w_g \ge 0 && \text{C7 bounds}
\end{aligned}
""")
    st.markdown('<div class="note">y<sub>a</sub> is whichever variable sits on arc a (a flight x or a wait w). '
                'x &le; 1 is implied: C1 to C3 move exactly one unit of flow. Every column of C1 to C3 has one +1 and one '
                '&minus;1, the incidence matrix of a directed graph, which is totally unimodular, so the LP optimum is '
                'already a whole-number itinerary. The tie term &tau;<sub>f</sub> is under $0.51 per trip and only orders '
                'equal prices:</div>', unsafe_allow_html=True)
    st.latex(r"\tau_f = 0.00003 + \mathbb{1}[f \in \mathrm{In}(\mathrm{ORD})] \cdot 0.5 \cdot \frac{\text{minutes after 00:00 CT of arrival}}{1440}")
    st.markdown('<div class="note">Ranks 2 to K add one no-good cut per itinerary already found, which breaks total '
                'unimodularity, so those solves declare x and w binary (an integer program solved by branch and bound):</div>',
                unsafe_allow_html=True)
    st.latex(r"\sum_{f \in P_j} x_f \le |P_j| - 1 \quad \text{for each earlier itinerary } P_j, \qquad x, w \in \{0, 1\}")

    st.subheader("Model size at this connection time")
    n_fl, n_nodes, n_waits = network_size(run_dir.name, mtime, mct)
    size_rows = []
    for s in SCENARIOS:
        r = tops[s.key]
        size_rows.append({"Scenario": s.label, "Variables": r.n_variables, "Constraints": r.n_constraints,
                          "Flights allowed": r.n_flights_allowed, "Status": r.status,
                          "Cheapest": f"${r.itineraries[0].cost}" if r.itineraries else "none"})
    st.dataframe(pd.DataFrame(size_rows), hide_index=True, width="stretch")
    st.caption(f"{n_fl} flights, {n_nodes} time nodes, {n_waits} wait arcs.")

    st.subheader(f"Checks for: {result.scenario.label}")
    if result.status == "optimal":
        n_vars = result.n_variables
        cross = abs(result.lp_objective - result.shortest_path_cost) < 1e-6
        st.markdown(
            f'<div class="note">Integrality: all {n_vars} variables are 0 or 1 at the LP optimum: '
            f'<b>{"yes" if result.integral else "no"}</b>.<br>Independent check: networkx shortest path cost '
            f'{result.shortest_path_cost:.5f} vs LP objective {result.lp_objective:.5f}: '
            f'<b>{"match" if cross else "MISMATCH"}</b>.</div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame([{"Rank": it.rank, "Price": f"${it.cost}", "Route": route_text(it.airports),
                                    "Solved as": it.method} for it in result.itineraries]),
                     hide_index=True, width="stretch")
    else:
        st.markdown('<div class="note">The LP is infeasible: no same-day path satisfies C1 to C6.</div>', unsafe_allow_html=True)
    st.download_button("Download the .lp model file", result.lp_text, file_name=f"mia_ord_{key}_mct{mct}.lp",
                       mime="text/plain")

    st.subheader("Every constraint")
    query = st.text_input("Search constraints", placeholder="for example C4, CLT_1405, or AA1204")
    groups = st.multiselect("Groups", ["C1", "C2", "C3", "C4", "C5", "C6", "CUT"],
                            default=["C1", "C2", "C3", "C4", "C5", "C6", "CUT"])
    cdf = pd.DataFrame([{"Group": c.group, "Name": c.name, "Expression": c.expression, "LHS at optimum": round(c.lhs, 4)}
                        for c in result.constraints])
    if not cdf.empty:
        cdf = cdf[cdf["Group"].isin(groups)]
        if query:
            mask = cdf["Name"].str.contains(query, case=False, regex=False) | cdf["Expression"].str.contains(query, case=False, regex=False)
            cdf = cdf[mask]
    st.caption(f"{len(cdf)} of {len(result.constraints)} constraints shown.")
    st.dataframe(cdf, hide_index=True, width="stretch", height=380)

    st.subheader("Assumptions and limitations")
    st.markdown("""
- **Separate tickets.** Each leg is priced as its own one-way ticket. Airlines price connecting trips as a whole, so a real single ticket can cost more or less. Separate tickets also carry no protection if a delay causes a missed connection.
- **Cheapest fare shown.** Prices are the lowest economy fare Google displays, often Basic Economy, with no bags.
- **Google's list may be incomplete**, for example codeshare duplicates.
- **Snapshot.** Prices change constantly; every number here is tied to the scrape time above.
- **Airport set.** Only these 22 airports are considered; a cheaper route through another airport would not be found.
- **"American"** means marketing carrier code AA, which includes American Eagle regional flights.
- **Terms of service.** Google Flights does not permit automated scraping. This was one low-volume, paced run for a class project.
""")

with tab_sens:
    if result.status != "optimal":
        st.info("Sensitivity needs a feasible LP. Change the scenario or the connection time.")
    else:
        st.subheader("Cheapest cost to reach each connecting airport")
        st.caption("Shortest-path label: the least you can pay to be at that airport, ready to depart, under this scenario.")
        st.plotly_chart(charts.reach_bars(result.reach_cost), width="stretch", config=PLOT_CONFIG)

        st.subheader("Shadow prices of the balance constraints")
        st.markdown('<div class="note">For each node n, &pi;<sub>C1</sub> + &pi;<sub>n</sub> is the cost-to-reach implied by '
                    'the LP duals. Along the optimal path it equals the shortest-path label. Elsewhere the LP is degenerate '
                    '(many dual solutions are optimal), so the dual can differ from the true label. Nodes that no trip from '
                    'Miami can reach are left out.</div>', unsafe_allow_html=True)
        implied = dual_labels(result)
        drows = []
        for name, value in implied.items():
            label = result.node_labels.get(name)
            if label is None:
                continue
            drows.append({"Node": name, "Airport": name.split("_")[0], "Dual-implied cost": round(value, 2),
                          "Shortest-path cost": round(label, 2),
                          "Agreement": "matches" if abs(label - value) <= 0.01 else "degenerate"})
        drows.sort(key=lambda r: (r["Agreement"] != "matches", r["Node"]))
        st.caption(f"{len(drows)} reachable nodes of {len(implied)}; "
                   f"{sum(1 for r in drows if r['Agreement'] == 'matches')} have a dual that matches the true label.")
        st.dataframe(pd.DataFrame(drows), hide_index=True, width="stretch", height=320)

        st.subheader("Closest calls: how much cheaper would a flight need to be?")
        st.markdown('<div class="note">For every flight the solver did not pick: the cheapest complete same-day trip that '
                    'uses it, and how far its price would have to drop before that trip ties the optimum. This is exact, '
                    'computed from shortest paths into and out of the flight. The simplex reduced cost is shown for '
                    'comparison: because the LP is degenerate it is often 0 for flights that cannot reach Chicago at all, '
                    'so it is only a lower bound here.</div>', unsafe_allow_html=True)
        rrows = []
        usable = [(fid, d) for fid, d in result.price_drop.items() if d is not None]
        for fid, drop in sorted(usable, key=lambda kv: kv[1])[:25]:
            f = flights_by_id[fid]
            rrows.append({"Flight": f.flight_number, "Route": f"{f.origin} → {f.dest}", "Depart": f"{f.dep:%H:%M}",
                          "Arrive": f"{f.arr:%H:%M}", "Price": f"${f.price}",
                          "Best trip using it": f"${int(result.lp_objective + drop)}",
                          "Price drop needed": f"${drop:.0f}" if drop >= 0.5 else "$0 (tie)",
                          "LP reduced cost": round(result.reduced_costs.get(fid, 0.0), 2)})
        st.caption(f"{len(usable)} unchosen flights can be part of a same-day trip; "
                   f"{len(result.price_drop) - len(usable)} cannot (no onward or inbound connection that day).")
        st.dataframe(pd.DataFrame(rrows), hide_index=True, width="stretch")

with tab_data:
    st.subheader("Cheapest nonstop price for every route")
    st.caption("Blank cells had no nonstop service on Nov 20. An x marks a search that failed.")
    st.plotly_chart(charts.price_heatmap(data["flights"], status), width="stretch", config=PLOT_CONFIG)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Routes with flights", n_ok)
    m2.metric("No nonstop service", sum(1 for v in status.values() if v == "no_service"))
    m3.metric("Failed searches", sum(1 for v in status.values() if v == "failed"))
    m4.metric("Not yet searched", len(search_routes()) - len(status))
    if data["drops"]:
        st.caption("Rows dropped during validation: " + ", ".join(f"{r.replace('_', ' ')} {n}" for r, n in sorted(data["drops"].items())))

    st.subheader("All scraped flights")
    df = pd.DataFrame(data["rows"])
    if not df.empty:
        f1, f2, f3 = st.columns(3)
        pick_airline = f1.multiselect("Airline", sorted(df["airline"].unique()))
        pick_from = f2.multiselect("From", sorted(df["origin"].unique()))
        pick_to = f3.multiselect("To", sorted(df["dest"].unique()))
        if pick_airline:
            df = df[df["airline"].isin(pick_airline)]
        if pick_from:
            df = df[df["origin"].isin(pick_from)]
        if pick_to:
            df = df[df["dest"].isin(pick_to)]
        st.dataframe(df, hide_index=True, width="stretch", height=420)
    if data["reference"]:
        st.subheader("Google single-ticket reference fares")
        ref_rows = []
        for which, ref in data["reference"].items():
            if ref:
                for leg in ref["legs"]:
                    ref_rows.append({"Search": "All airlines" if which == "all" else "American", "Total": f"${ref['price']}",
                                     "Flight": leg["flight_number"], "From": leg["origin"], "To": leg["dest"],
                                     "Depart": leg["dep_local"], "Arrive": leg["arr_local"]})
        st.dataframe(pd.DataFrame(ref_rows), hide_index=True, width="stretch")
