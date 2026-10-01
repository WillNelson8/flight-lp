# MIA to ORD: cheapest same-day route as a linear program

Finds the cheapest way to fly from Miami (MIA) to Chicago O'Hare (ORD) on **Friday, November 20, 2026**, using real prices scraped from Google Flights. The trip may be direct or connect through any of 20 other US airports, any number of times, as long as it all happens that day. It is solved four ways (American only or all airlines, any stops or one stop at most), with the top K itineraries ranked by price.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python fetch.py          # scrape today's prices (about 30 minutes, resumable)
.venv/bin/python model.py          # solve all four scenarios, print a report, write out/S1..S4.lp
.venv/bin/streamlit run dashboard.py
.venv/bin/pytest                   # 37 tests, no network needed
```

`fetch.py` pauses 2 to 4 seconds between searches. If Google blocks it, it stops after 5 failures in a row and keeps everything collected. Run it again later to resume. `model.py --partial` and the dashboard both work on an unfinished scrape and label it as partial.

## The model

The flights form a **time-space network**. A node is an airport at a specific time: each departure, and each arrival plus the minimum connection time (default 45 minutes). Flight arcs carry the ticket price. Zero-cost wait arcs join consecutive nodes at the same airport. Every arc moves forward in time, so there are no cycles.

```
min   sum_f (p_f + tau_f) x_f
s.t.  C1  sum of x_f over flights leaving MIA = 1
      C2  sum of x_f over flights landing at ORD = 1
      C3  inflow - outflow = 0 at every (airport, time) node
      C4  x_f = 0 for flights landing at ORD after 23:59 Central
      C5  x_f = 0 for non-American flights        (American scenarios)
      C6  x_f = 0 for hub-to-hub flights          (one-stop scenarios)
      C7  x_f >= 0, w_g >= 0
```

- **Whole-number answers.** Every column of C1 to C3 has one +1 and one -1, the incidence matrix of a directed graph. That makes the constraint matrix totally unimodular, so the plain LP returns a whole 0/1 itinerary. The code checks this on every solve.
- **Tie term.** `tau_f`, under $0.51 per trip, only breaks ties between equal prices: earlier ORD arrival wins, then fewer flights.
- **Ranks 2 to K.** These add a no-good cut per earlier itinerary, `sum over f in P of x_f <= |P| - 1`. That breaks total unimodularity, so those solves are integer programs (CBC branch and bound).
- **Independent cross-check.** networkx shortest path on the same network must equal the LP optimum.

## Files

| File | What it does |
|---|---|
| `airports.py` | The 22 airports and the 421 directed routes searched |
| `fetch.py` | Builds Google Flights queries (via `fast-flights`), parses both of Google's result lists, validates, saves |
| `snapshot.py` | Run directory format: `data/<stamp>/flights.csv`, `routes.csv`, `drops.csv`, `reference.json` |
| `network.py` | Time-space network builder |
| `model.py` | PuLP model, scenarios, K-best cuts, duals, exact price-drop sensitivity, CLI report |
| `charts.py` | Plotly figures: route map, time-space diagram, bar charts, price heatmap |
| `dashboard.py` | Streamlit dashboard |
| `data/spot_check.md` | Snapshot compared against the live Google Flights site |

## Assumptions and limitations

- **Separate tickets.** Each leg is priced as its own one-way ticket. A real single ticket for the same flights can cost more or less. Google's single-ticket fare is shown for comparison. Separate tickets have no protection if a delay causes a missed connection.
- **Cheapest fare only.** Prices are the lowest economy fare Google shows, often Basic Economy, with no bags.
- **22 airports only.** A cheaper route through an airport outside the 22 would not be found.
- **Snapshot.** Prices change constantly. Every result is tied to its scrape time.
- **"American"** means marketing carrier code AA, which includes American Eagle regional flights.
- **Terms of service.** Google Flights does not permit automated scraping. This project makes one paced, low-volume run for a class assignment.
