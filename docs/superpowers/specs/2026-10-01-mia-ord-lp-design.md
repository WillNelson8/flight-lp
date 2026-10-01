# MIA to ORD Cheapest Same-Day Route: LP Design Spec

Date: 2026-10-01
Status: Draft for review

## 1. Purpose

A class assignment for a linear programming / operations research course. Find the cheapest way to fly from Miami (MIA) to Chicago O'Hare (ORD) on **Friday, November 20, 2026**, using real prices scraped on the day the code runs. The route may be direct or pass through any number of intermediate airports, as long as the whole trip happens on Nov 20.

The linear program formulation and its constraints are the primary deliverable. The dashboard exists to show that formulation and its solution clearly and graphically.

## 2. Questions answered

1. Cheapest same-day itinerary using **American Airlines only**.
2. Cheapest same-day itinerary using **all airlines**.
3. The same two questions restricted to **at most one stop**, for comparison.
4. For each of the four scenarios, the **top K itineraries ranked by cost** (cheapest, second cheapest, and so on).
5. How the LP answer compares with **Google's cheapest single-ticket fare** for MIA to ORD.

## 3. Scope

In scope:
- Scraping real nonstop flight data for Nov 20, 2026 between 22 airports.
- A time-space network LP solved with PuLP (CBC).
- K-best itineraries via no-good cuts.
- A Streamlit dashboard with a map, time-space diagram, LP formulation, sensitivity, and data views.
- Automated tests on small hand-built networks.

Out of scope:
- Booking, fare alerts, or any repeated/scheduled scraping.
- Baggage fees, seat fees, fare classes other than the cheapest economy fare Google shows.
- Airports beyond the 22 listed below.
- Multi-passenger or round-trip pricing.

## 4. Airports

Origin and destination: **MIA** (America/New_York) and **ORD** (America/Chicago).

The 20 intermediate airports, a mix of hubs and mid-size airports (editable as one list in `airports.py`):

| Group | Airports |
|---|---|
| Large hubs | ATL, CLT, DFW, DCA, PHL, DTW, IAH, EWR |
| Mid-size and smaller | BNA, RDU, CVG, CLE, CMH, IND, PIT, MSY, JAX, MEM, STL, SAV |

`airports.py` stores, for each of the 22 airports: IATA code, city name, latitude, longitude, and IANA time zone (all are in America/New_York, America/Chicago, or America/Indiana/Indianapolis). Time zone conversion uses Python's `zoneinfo`, never hard-coded offsets. Nov 20, 2026 is after the Nov 1 DST change, so all airports are on standard time; `zoneinfo` handles this automatically.

## 5. Data acquisition (`fetch.py`)

### 5.1 Source

Google Flights, queried through the `fast-flights` Python library (3.1.0, no API key). Backup: a Playwright headless-browser scraper that writes the same output format, used only if `fast-flights` stops working.

Verified on 2026-10-01 against real responses: the library's own parser (`get_flights`) reads only Google's "other flights" list and drops the "best flights" list and flight numbers (MIA to ORD nonstop: it returned 10 of 13 flights). So `fetch.py` uses `fast_flights.create_query` and `fast_flights.fetch_flights_html` to build and send the request, and parses Google's embedded result payload (the `script.ds:1` block) itself, reading both lists. Facts confirmed from real payloads:

- Result lists live at `payload[2][0]` (best) and `payload[3][0]` (other); both are `null` when a route has no nonstop service.
- Per itinerary: `k[1][0][1]` is the price in whole US dollars; `k[0][2]` is the list of legs.
- Per leg: `[3]` origin code, `[6]` destination code, `[8]` / `[10]` local departure / arrival time as `[hour, minute]` with omitted zero components (`[7]` means 07:00, `[null, 31]` means 00:31), `[20]` / `[21]` local departure / arrival date, `[22]` = `[carrier code, flight number, _, airline name]`, `[17]` aircraft.
- A response with no `script.ds:1` block is a block or CAPTCHA page and counts as a failure.

### 5.2 Searches

Every directed pair `(o, d)` with `o` in {MIA} plus the 20 hubs, `d` in the 20 hubs plus {ORD}, and `o != d`:

- MIA to each of 20 hubs, plus MIA to ORD: 21 searches
- Each hub to the 19 other hubs and to ORD: 20 x 20 = 400 searches
- Total: **421 searches**, all for departure date 2026-11-20, 1 adult, economy, one-way.

Each search keeps **nonstop flights only** (stops = 0), using the library's stops filter if available, otherwise filtering results.

Two additional reference searches, MIA to ORD with any number of stops and `hide_separate_and_self_transfer=True`: one with all airlines, one with `airlines=["AA"]`. The cheapest itinerary from each is recorded as Google's **single-ticket reference fare** (for example, on 2026-10-01 Google's cheapest was Frontier MIA-ATL-ORD at $163).

### 5.3 Pacing and resumability

- Random 2 to 4 second pause between searches.
- Each route's result is written to disk as soon as it completes. A re-run skips routes already marked `ok` or `no_service`.
- After 5 consecutive failures (errors, blocks, or CAPTCHA pages), the fetch stops, keeps everything collected, and prints a message to resume later. It never attempts to bypass a CAPTCHA.

### 5.4 Output files (`data/`)

Each run writes a directory `data/<YYYY-MM-DD_HHMM>/` (path overridable with the `FLIGHT_LP_DATA` environment variable). `flights.csv` has one row per nonstop flight:

| Column | Meaning |
|---|---|
| `origin`, `dest` | IATA codes of the searched route |
| `carrier` | Two-letter marketing carrier code (for example AA, UA, F9) |
| `airline` | Airline name as Google reports it |
| `flight_number` | Carrier code plus number, for example `AA 1204` |
| `dep_local`, `arr_local` | ISO 8601 local times with UTC offset |
| `price_usd` | Cheapest one-way economy price shown, in whole dollars |
| `is_american` | True if `carrier == "AA"` (American Eagle regional flights, such as AA 4097 CVG to ORD operated on an Embraer 170, carry code AA, verified) |
| `scraped_at` | UTC timestamp of that search |

`routes.csv`, one row per search attempt (the last row per route wins): `origin`, `dest`, `status` (`ok`, `no_service`, `failed`), `n_flights`, `scraped_at`.

`drops.csv`: validation drop counts per route and reason.

`reference.json`: Google's cheapest single-ticket MIA to ORD itinerary (any airline) and cheapest American itinerary, with legs, times, and price.

An empty `COMPLETE` file marks a finished run; the newest complete run is the one the solver and dashboard use. The solver and dashboard read only these files; they never scrape.

### 5.5 Validation

Rows are dropped, and the drop counted by reason, if: price is missing or not positive; arrival is not after departure (in UTC); departure date is not 2026-11-20 local; stops != 0; origin or destination is not one of the 22 airports. Drop counts are saved and shown in the dashboard's Data tab.

### 5.6 Accuracy spot check

After scraping, 3 routes (MIA-ORD, one MIA-hub route, one hub-ORD route) are compared against the live Google Flights website in a browser. The comparison (match, or the difference and likely reason) is recorded in `data/spot_check.md`.

### 5.7 No fabricated numbers

No price, time, or flight in any output is ever invented or estimated. Missing data is shown as missing.

## 6. Network model (`network.py`)

A time-space network built from one snapshot and one minimum connection time (MCT, default 45 minutes).

All times are converted to UTC for computation and displayed in each airport's local time.

**Nodes.** An event node `(a, t)` exists at intermediate airport `a` for:
- each departure time `t` of a flight leaving `a`, and
- each time `t = arrival + MCT` of a flight landing at `a`.

Events at the same airport and the same time share one node. MIA and ORD have no event nodes: MIA is handled by constraint C1 (start) and ORD by C2 (end).

**Arcs.**
- Flight arc for each flight `f`: from its origin's departure node (or MIA) to its destination's `arrival + MCT` node (or ORD). Cost = `price_usd`.
- Wait arc between each pair of consecutive event nodes at the same airport. Cost = 0.

Because every arc moves forward in time, the network has no cycles.

## 7. The linear program (`model.py`)

### 7.1 Formulation

```
Sets
  F           flights (after validation)
  W           wait arcs
  N           event nodes at intermediate airports
  Out(MIA)    flights departing MIA
  In(ORD)     flights arriving ORD
  in(n), out(n)  arcs (flight or wait) entering / leaving node n

Variables
  x_f  for f in F     1 if flight f is taken      0 <= x_f <= 1
  w_g  for g in W     1 if waiting on arc g       0 <= w_g <= 1

Objective
  minimize   sum over f in F of  (price_f + tie_f) * x_f

  tie_f is a tie-breaker far smaller than $1 (prices are whole dollars):
    tie_f = 0.00003                                   for every flight (fewer flights wins a tie)
          + 0.5 * (minutes after 00:00 CT of ORD arrival) / 1440   for f in In(ORD) (earlier arrival wins)
  One minute of arrival time is worth $0.00035, more than ten extra flights ($0.0003).
  The total tie term of any itinerary is below $0.51, so it never changes which
  price is cheapest; it only orders itineraries of equal price. Reported costs
  are the pure sum of price_f.

Constraints
  C1 Start       sum over f in Out(MIA) of x_f = 1
  C2 End         sum over f in In(ORD) of x_f = 1
  C3 Balance     for each n in N:  sum over in(n) - sum over out(n) = 0
  C4 Same day    x_f = 0  for each f in In(ORD) arriving after 2026-11-20 23:59 America/Chicago
  C5 Airline     x_f = 0  for each f with is_american = False    (American scenarios only)
  C6 One stop    x_f = 0  for each f not in Out(MIA) and not in In(ORD)   (one-stop scenarios only)
  C7 Bounds      x_f >= 0,  w_g >= 0   (x <= 1 is implied: C1 to C3 move exactly one unit of flow)
```

"One day" means: depart MIA on 2026-11-20 local time (guaranteed by the search date) and arrive ORD no later than 23:59 Central on 2026-11-20 (C4). Since time only moves forward, every intermediate leg also falls inside that window.

C4, C5, and C6 are written into the model as explicit `x_f = 0` rows, rather than silently filtered, so they appear in the constraint table and the `.lp` file.

### 7.2 Why the LP gives a whole-number answer

With C1 written as a supply of 1 at MIA and C2 as a demand of 1 at ORD, every variable's column has exactly one +1 and one -1 across C1 to C3. That is the incidence matrix of a directed graph, which is totally unimodular. Adding single-variable rows (C4 to C6) preserves this. Upper bounds of 1 are not declared because C1 to C3 already imply them; leaving them off keeps every chosen variable basic in the simplex solution, so the duals read cleanly as cost-to-reach labels. So every vertex of the feasible region is 0/1, and the simplex solution is a real itinerary. After every LP solve, the code checks that every variable is within 1e-6 of 0 or 1 and reports the result.

### 7.3 Scenarios

| Scenario | C5 American | C6 One stop |
|---|---|---|
| S1 American, any stops | on | off |
| S2 American, one stop at most | on | on |
| S3 All airlines, any stops | off | off |
| S4 All airlines, one stop at most | off | on |

### 7.4 K-best itineraries

1. Solve the LP. The result is itinerary P1.
2. Add a no-good cut for P1: `sum over f in P1 of x_f <= |P1| - 1`. Re-solve to get P2.
3. Repeat, accumulating cuts, until K itineraries are found or the model is infeasible.

The cuts break total unimodularity, so solves 2 through K declare `x` and `w` as binary (an integer program, CBC branch and bound). The dashboard labels solve 1 as "LP" and solves 2 to K as "IP with cuts".

Ranking is by total price (the objective). Two itineraries with the same airports but different flights are different itineraries. Ties in price are broken inside the objective by the tie term (earlier ORD arrival first, then fewer flights), so the ranking is deterministic. Real data has many ties (on 2026-10-01 all 13 MIA-ORD nonstops were $227), so this matters.

K defaults to 5, adjustable 1 to 10. If fewer than K itineraries exist, all that exist are returned.

### 7.5 Sensitivity outputs (from solve 1, the pure LP)

- **Dual values** of C1 to C3, as reported by CBC.
- **Shortest-path labels**: the cheapest cost to reach each node, computed independently by networkx. Shown next to the dual values. Where they differ, the table notes that the LP is degenerate at that node and its dual is not unique.
- **Reduced costs** of flights not chosen: how much the price would need to drop before the flight could enter the solution.

### 7.6 Infeasibility

If a scenario has no feasible itinerary (no same-day path exists), `model.py` returns a "no feasible itinerary" result instead of raising.

### 7.7 Command-line report

`python model.py` prints, for each scenario: model size (variables, constraints), the top K itineraries with legs and prices, the integrality check result, and the networkx cross-check result. It also writes `out/<scenario>.lp`.

## 8. Dashboard (`dashboard.py`, figures in `charts.py`)

Streamlit, launched with `streamlit run dashboard.py`.

**Visual style:**
- Light background, single blue accent, gray for context.
- Inter font, tabular figures for numbers.
- No emojis anywhere.
- Every chart has hover tooltips.
- Chart colors are validated with the dataviz palette validator before shipping.

### 8.1 Header

- Title: MIA to ORD, Friday Nov 20, 2026.
- Data line, from the snapshot: scrape timestamp, flight count, and route coverage (for example "612 nonstop flights across 421 routes, scraped Oct 1, 2026 2:30 PM ET").

### 8.2 Summary row

Five tiles:
- One tile per scenario S1 to S4, showing the #1 itinerary's price, route, number of stops, and departure and arrival times.
- One tile for Google's single-ticket reference fare.

The cheapest tile is highlighted. A scenario with no feasible itinerary shows "No feasible itinerary".

### 8.3 Controls row

All controls re-solve the model. Results are cached by (scenario, MCT, K).
- Airline: American / All
- Stops: Any / One at most
- Minimum connection time: 30 to 120 minutes, step 15, default 45
- K: 1 to 10, default 5

### 8.4 Tab 1: Solution

- **Route map.** Plotly geo map of the US showing all 22 airports.
  - Faint gray lines show every airport pair with service.
  - The top K itineraries for the selected scenario are drawn in a single-hue blue ramp. #1 is darkest and thickest; each later rank is lighter and thinner. Each line carries a rank badge.
  - When several ranked itineraries share an airport pair, their lines are drawn as slightly offset curves so all of them stay visible.
  - A toggle (on by default) overlays the #1 itinerary of the other airline filter as a dashed line.
  - A ranked list sits beside the map. Selecting a row highlights only that itinerary; "Show all" restores every rank.
- **Time-space diagram.**
  - The x axis is time of day in Eastern Time, labeled as such.
  - The y axis lists airports, MIA at the top and ORD at the bottom.
  - Every flight is a thin gray segment. The top K itineraries are drawn in the same blue ramp as the map, with waits shown as horizontal segments.
- **Itinerary table** for the selected rank: leg, airline, flight number, local departure and arrival, layover, price, and running total.
- **Comparison bar chart.** Horizontal bars for the #1 price of S1 to S4 plus Google's reference, in one hue, with the cheapest emphasized.

### 8.5 Tab 2: The linear program

- **Formulation** (section 7.1) typeset with `st.latex`.
- **Model size** per scenario: variables, constraints, flights.
- **Constraint table**, searchable: group (C1 to C6, cuts), name, expression, and whether it is binding at the optimum.
- **Integrality check** result, plus an "LP" or "IP with cuts" label for each rank.
- **Download** of the `.lp` file for the selected scenario.

### 8.6 Tab 3: Sensitivity

- Bar chart of the cheapest cost to reach each intermediate airport (minimum shortest-path label across its nodes).
- Table of dual values next to the shortest-path labels, with degeneracy notes.
- Table of the 20 non-chosen flights with the smallest reduced costs.

### 8.7 Tab 4: Data

- **Heatmap.** Rows are origins (MIA plus the 20 hubs), columns are destinations (the 20 hubs plus ORD). Each cell is shaded by the cheapest nonstop price on a sequential blue scale. Cells with no service are blank, and failed scrapes are marked distinctly.
- **Route coverage** counts: ok, no_service, failed.
- **Validation drop counts** by reason.
- **Raw flight table**, filterable by airline and route.

## 9. Error handling summary

| Situation | Behavior |
|---|---|
| Google blocks or shows a CAPTCHA | Stop after 5 consecutive failures, keep progress, resume later |
| Route has no nonstop flights | `no_service` status, not an error |
| Malformed or out-of-scope row | Dropped, counted by reason |
| `fast-flights` breaks entirely | Switch to the Playwright backup scraper (same output format) |
| No snapshot exists yet | Dashboard shows a message to run `fetch.py` first |
| Scenario infeasible | "No feasible itinerary" result |
| Fewer than K itineraries | Return all that exist |

## 10. Testing (`tests/`, pytest)

Hand-built networks with known answers. No test touches the network.

1. Direct flight is cheapest: it is chosen.
2. A connection is cheaper than the direct flight: the connection is chosen.
3. A connection tighter than MCT is never used.
4. Eastern and Central time zone conversion produces correct connection feasibility.
5. A flight landing at ORD after 23:59 Central is excluded by C4.
6. The American filter (C5) skips a cheaper non-American flight.
7. The one-stop rule (C6) blocks a cheaper two-stop route.
8. K-best returns itineraries in the correct order on a network with known 2nd and 3rd cheapest.
9. The integrality check passes on LP solves.
10. An infeasible scenario returns "no feasible itinerary".
11. On each test network, the LP's #1 cost equals networkx shortest path on the same graph.
12. The scraper's parser correctly converts a saved sample `fast-flights` result to snapshot rows (fixture captured once from the real library).

## 11. Project layout

```
flight-lp/
  README.md            how to install, fetch, solve, and run the dashboard
  requirements.txt     fast-flights, pulp, streamlit, plotly, pandas, networkx, pytest
  airports.py          the 22 airports
  fetch.py             scraper (section 5)
  network.py           time-space network builder (section 6)
  model.py             LP, K-best, sensitivity, CLI report (section 7)
  charts.py            Plotly figure builders (section 8)
  dashboard.py         Streamlit layout and controls (section 8)
  data/                snapshots, route status, reference fares, spot check
  out/                 generated .lp files
  tests/               pytest suite and fixtures
  docs/superpowers/specs/  this spec
```

Python 3.11 (the machine has Anaconda Python 3.11.7) in a project virtual environment at `flight-lp/.venv`.

## 12. Assumptions and known limitations

These are stated on the dashboard's LP tab and in the README.

- **Separate tickets.** Each leg is priced as its own one-way ticket. Airlines price connecting itineraries as a whole, so a real single ticket can cost more or less than the sum of its legs. Google's single-ticket reference fare is shown for comparison. Separate tickets also have no protection if a delay causes a missed connection.
- **Cheapest fare shown.** The price is the lowest economy fare Google displays, often Basic Economy, with no bags.
- **Google's list may be incomplete.** Google Flights may omit some flights (for example codeshare duplicates).
- **Prices are a snapshot.** They change constantly. Results are tied to the scrape timestamp.
- **Airport set.** Only the 22 listed airports are considered. A cheaper route through an unlisted airport would not be found.
- **Terms of service.** Google Flights' terms do not permit automated scraping. The single low-volume, paced run is for a class project only.
- **"American".** A flight counts as American if its marketing carrier code is AA, which includes American Eagle regional flights.

## 13. Success criteria

1. Every one of the 421 routes ends with status `ok` or `no_service` (zero `failed`), after resumes if needed.
2. All tests pass.
3. For all four scenarios on the real snapshot:
   - The LP #1 cost equals the networkx shortest path cost.
   - The integrality check passes.
4. The spot check is recorded for 3 routes.
5. The dashboard starts with `streamlit run dashboard.py` and shows all four tabs with no errors. The map shows the top K itineraries for each scenario. Every number on screen traces back to the snapshot files.
