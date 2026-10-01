# Spot check: scraped snapshot vs live Google Flights

Checked 2026-10-01 at 4:10 PM EDT in a browser against run `2026-10-01_1558`. Every search: 2026-11-20, one-way, 1 adult, economy, nonstop only, USD.

| Route | Snapshot (scraped, UTC) | Live Google Flights | Result |
|---|---|---|---|
| MIA to ORD | 13 nonstops, all $227 (19:59) | "13 results returned", all $227, same 13 departure/arrival times | Match |
| MIA to ATL | 21 nonstops: F9 $59 x2, F9 $79, AA $134 x7, DL $144 x4, DL $174 x5, DL $239 x2 (19:58) | "21 results returned", same 21 times and prices | Match |
| ATL to ORD | 22 nonstops: F9 $109 x2, AA/UA $171 x10, AA $229, DL $269 x3, UA $288, DL $329 x4, DL $389 (20:00) | "22 results returned", same 22 times and prices | Match |

Notes:
- MIA to ORD shows 3 "Top flights" plus 10 "Other flights" on the live page. The snapshot has all 13 because `fetch.py` parses both lists (the fast-flights library's own parser returns only the 10 "other" flights).
- The live MIA to ATL page labels AA 3573 (8:54 PM) "Operated by Envoy Air as American Eagle". The snapshot records it with carrier AA, so it counts as American, as intended.
- The 10:07 PM MIA to ORD flight lands at 12:47 AM the next day on both; the snapshot dates its arrival 2026-11-21, so the same-day constraint (C4) excludes it.
