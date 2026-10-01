"""Plotly figure builders for the dashboard. Pure functions: data in, figure out."""
from zoneinfo import ZoneInfo

import plotly.graph_objects as go

from airports import AIRPORTS, DEST, HUBS, ORIGIN

INK = "#0E1B2E"
INK_2 = "#41536B"
MUTED = "#64748B"
GRID = "#E2E8F0"
CONTEXT = "#CBD5E1"
SURFACE = "#FFFFFF"
LAND = "#F1F5F9"
FONT = dict(family="Inter, -apple-system, Segoe UI, sans-serif", color=INK, size=13)
ET = ZoneInfo("America/New_York")

# Ordinal blue ramp, validated with the dataviz checker on white: one hue, monotone lightness,
# adjacent lightness gap >= 0.06, light end above 2:1. Ten steps cannot clear the gap check, so
# ranks past 5 reuse the lightest tone and are told apart by their number badge and a dotted line.
RANK_TONES = ["#0d366b", "#184f95", "#256abf", "#3987e5", "#6da7ec"]
BAR_LIGHT = "#86b6ef"
BAR_DARK = "#184f95"
SEQUENTIAL = [[0.0, "#e6f0fc"], [0.5, "#9ec5f4"], [1.0, "#3987e5"]]


def rank_color(rank: int) -> str:
    return RANK_TONES[min(rank, len(RANK_TONES)) - 1]


def rank_width(rank: int) -> float:
    return max(1.5, 5 - 0.4 * (rank - 1))


def rank_dash(rank: int) -> str:
    return "solid" if rank <= len(RANK_TONES) else "dot"


def _layout(fig: go.Figure, height: int, **kwargs) -> go.Figure:
    kwargs.setdefault("margin", dict(l=8, r=8, t=8, b=8))
    fig.update_layout(
        height=height, paper_bgcolor=SURFACE, plot_bgcolor=SURFACE, font=FONT, showlegend=False,
        hoverlabel=dict(bgcolor="white", bordercolor=GRID, font=dict(family=FONT["family"], color=INK, size=12)),
        **kwargs,
    )
    return fig


def _leg_text(f) -> str:
    return (f"{f.flight_number} {f.origin} to {f.dest}<br>{f.dep:%H:%M} to {f.arr:%H:%M} local<br>"
            f"${f.price} ({f.airline})")


def _curve(a: str, b: str, offset: float, n: int = 31) -> tuple[list[float], list[float]]:
    """Quadratic Bezier from airport a to b, bowed sideways by `offset` (a fraction of the leg length)."""
    x0, y0 = AIRPORTS[a].lon, AIRPORTS[a].lat
    x2, y2 = AIRPORTS[b].lon, AIRPORTS[b].lat
    dx, dy = x2 - x0, y2 - y0
    cx, cy = (x0 + x2) / 2 - dy * offset, (y0 + y2) / 2 + dx * offset
    lons, lats = [], []
    for i in range(n):
        t = i / (n - 1)
        lons.append((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x2)
        lats.append((1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y2)
    return lons, lats


def route_map(flights, itineraries, highlight: int | None = None, compare=None) -> go.Figure:
    fig = go.Figure()
    pairs = sorted({(f.origin, f.dest) for f in flights})
    lons, lats = [], []
    for a, b in pairs:
        lons += [AIRPORTS[a].lon, AIRPORTS[b].lon, None]
        lats += [AIRPORTS[a].lat, AIRPORTS[b].lat, None]
    fig.add_trace(go.Scattergeo(lon=lons, lat=lats, mode="lines", line=dict(color=CONTEXT, width=1),
                                hoverinfo="skip", name="context"))

    if compare is not None:
        for f in compare.flights:
            lo, la = _curve(f.origin, f.dest, -0.18)
            fig.add_trace(go.Scattergeo(lon=lo, lat=la, mode="lines", line=dict(color=MUTED, width=2, dash="dash"),
                                        hoverinfo="text", text=[f"Other airline filter #1<br>{_leg_text(f)}"] * len(lo),
                                        name="compare"))

    shared = {}
    for it in itineraries:
        for f in it.flights:
            shared.setdefault((f.origin, f.dest), []).append(it.rank)
    for it in sorted(itineraries, key=lambda i: -i.rank):  # draw #1 last so it sits on top
        opacity = 1.0 if highlight in (None, it.rank) else 0.15
        lons, lats, texts = [], [], []
        for f in it.flights:
            ranks = shared[(f.origin, f.dest)]
            j = ranks.index(it.rank)
            offset = 0.08 + (j - (len(ranks) - 1) / 2) * 0.12
            lo, la = _curve(f.origin, f.dest, offset)
            lons += lo + [None]
            lats += la + [None]
            texts += [f"#{it.rank}  ${it.cost}<br>{_leg_text(f)}"] * len(lo) + [None]
        fig.add_trace(go.Scattergeo(
            lon=lons[:-1], lat=lats[:-1], mode="lines", opacity=opacity, name=f"rank {it.rank}",
            line=dict(color=rank_color(it.rank), width=rank_width(it.rank), dash=rank_dash(it.rank)),
            hoverinfo="text", text=texts[:-1],
        ))
        mid_leg = it.flights[len(it.flights) // 2]
        ranks = shared[(mid_leg.origin, mid_leg.dest)]
        j = ranks.index(it.rank)
        lo, la = _curve(mid_leg.origin, mid_leg.dest, 0.08 + (j - (len(ranks) - 1) / 2) * 0.12)
        fig.add_trace(go.Scattergeo(
            lon=[lo[15]], lat=[la[15]], mode="markers+text", opacity=opacity, name=f"badge {it.rank}",
            marker=dict(size=17, color="white", line=dict(color=rank_color(it.rank), width=1.6)),
            text=[str(it.rank)], textfont=dict(color=INK, size=10, family=FONT["family"]),
            hoverinfo="skip",
        ))

    codes = list(AIRPORTS)
    fig.add_trace(go.Scattergeo(
        lon=[AIRPORTS[c].lon for c in codes], lat=[AIRPORTS[c].lat for c in codes], mode="markers+text",
        marker=dict(size=[11 if c in (ORIGIN, DEST) else 7 for c in codes], color=INK_2,
                    line=dict(color="white", width=1)),
        text=codes, textposition="top center", textfont=dict(size=10, color=INK_2, family=FONT["family"]),
        hovertext=[f"{c} {AIRPORTS[c].city}" for c in codes], hoverinfo="text", name="airports",
    ))
    fig.update_geos(scope="usa", projection_type="albers usa", fitbounds="locations", showland=True,
                    landcolor=LAND, subunitcolor="white", countrycolor="white", showlakes=False, bgcolor=SURFACE)
    return _layout(fig, 520)


def _airport_order() -> list[str]:
    return [ORIGIN] + sorted(HUBS, key=lambda c: -AIRPORTS[c].lon) + [DEST]


def _et(dt):
    return dt.astimezone(ET).replace(tzinfo=None)


def time_space(flights, itineraries, highlight: int | None = None) -> go.Figure:
    fig = go.Figure()
    xs, ys = [], []
    for f in flights:
        xs += [_et(f.dep), _et(f.arr), None]
        ys += [f.origin, f.dest, None]
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=CONTEXT, width=1), hoverinfo="skip", name="context"))

    for it in sorted(itineraries, key=lambda i: -i.rank):
        opacity = 1.0 if highlight in (None, it.rank) else 0.15
        xs, ys, texts = [], [], []
        for f in it.flights:
            xs += [_et(f.dep), _et(f.arr)]
            ys += [f.origin, f.dest]
            texts += [f"#{it.rank}  depart {f.origin}<br>{_leg_text(f)}", f"#{it.rank}  arrive {f.dest}<br>{_leg_text(f)}"]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers", opacity=opacity, name=f"rank {it.rank}",
            line=dict(color=rank_color(it.rank), width=rank_width(it.rank), dash=rank_dash(it.rank)),
            marker=dict(size=8, color=rank_color(it.rank), line=dict(color="white", width=1)),
            hoverinfo="text", text=texts,
        ))
    order = _airport_order()
    fig.update_yaxes(categoryorder="array", categoryarray=order[::-1], showgrid=True, gridcolor=GRID,
                     tickfont=dict(color=INK_2, size=11), fixedrange=True)
    fig.update_xaxes(title=dict(text="Eastern Time, Nov 20", font=dict(color=INK_2, size=12)), showgrid=True,
                     gridcolor=GRID, tickformat="%H:%M", tickfont=dict(color=INK_2))
    return _layout(fig, 560)


def cost_bars(items: list[tuple[str, int | None]]) -> go.Figure:
    labels = [label for label, _ in items]
    costs = [c for _, c in items]
    known = [c for c in costs if c is not None]
    cheapest = min(known) if known else None
    fig = go.Figure(go.Bar(
        y=labels, x=[c or 0 for c in costs], orientation="h",
        marker=dict(color=[BAR_DARK if c is not None and c == cheapest else BAR_LIGHT for c in costs],
                    line=dict(color="white", width=2), cornerradius=4),
        text=[f"${c}" if c is not None else "" for c in costs], textposition="outside",
        textfont=dict(color=INK, size=12), hovertemplate="%{y}: $%{x}<extra></extra>", cliponaxis=False,
    ))
    for label, c in items:
        if c is None:
            fig.add_annotation(x=0, y=label, text="no feasible itinerary", showarrow=False, xanchor="left",
                               font=dict(color=MUTED, size=12))
    fig.update_yaxes(autorange="reversed", tickfont=dict(color=INK_2))
    fig.update_xaxes(showgrid=True, gridcolor=GRID, tickprefix="$", rangemode="tozero", tickfont=dict(color=INK_2))
    return _layout(fig, 60 + 44 * len(items), margin=dict(l=8, r=48, t=8, b=8))


def reach_bars(reach: dict[str, int]) -> go.Figure:
    items = sorted(reach.items(), key=lambda kv: kv[1])
    fig = go.Figure(go.Bar(
        y=[f"{a} {AIRPORTS[a].city}" for a, _ in items], x=[c for _, c in items], orientation="h",
        marker=dict(color=RANK_TONES[3], line=dict(color="white", width=2), cornerradius=4),
        text=[f"${c}" for _, c in items], textposition="outside", textfont=dict(color=INK, size=11),
        hovertemplate="%{y}: $%{x}<extra></extra>", cliponaxis=False,
    ))
    fig.update_yaxes(autorange="reversed", tickfont=dict(color=INK_2, size=11))
    fig.update_xaxes(showgrid=True, gridcolor=GRID, tickprefix="$", rangemode="tozero", tickfont=dict(color=INK_2))
    return _layout(fig, 60 + 24 * max(len(items), 1), margin=dict(l=8, r=48, t=8, b=8))


def price_heatmap(flights, route_status: dict[tuple[str, str], str]) -> go.Figure:
    origins = [ORIGIN] + HUBS
    dests = HUBS + [DEST]
    cheapest = {}
    for f in flights:
        key = (f.origin, f.dest)
        cheapest[key] = min(cheapest.get(key, f.price), f.price)
    z, text = [], []
    for o in origins:
        z_row, t_row = [], []
        for d in dests:
            price = cheapest.get((o, d))
            z_row.append(price)
            if price is not None:
                t_row.append(f"${price}")
            elif route_status.get((o, d)) == "failed":
                t_row.append("x")
            else:
                t_row.append("")
        z.append(z_row)
        text.append(t_row)
    fig = go.Figure(go.Heatmap(
        z=z, x=dests, y=origins, text=text, texttemplate="%{text}", textfont=dict(size=9, color=INK),
        colorscale=SEQUENTIAL, xgap=2, ygap=2, hoverongaps=False,
        hovertemplate="%{y} to %{x}: cheapest nonstop $%{z}<extra></extra>",
        colorbar=dict(title=dict(text="USD", font=dict(color=INK_2, size=11)), tickprefix="$", thickness=10,
                      outlinewidth=0, tickfont=dict(color=INK_2, size=10)),
    ))
    fig.update_yaxes(autorange="reversed", title=dict(text="from", font=dict(color=INK_2)), tickfont=dict(color=INK_2, size=11))
    fig.update_xaxes(side="top", title=dict(text="to", font=dict(color=INK_2)), tickfont=dict(color=INK_2, size=11))
    return _layout(fig, 640, margin=dict(l=8, r=8, t=48, b=8))
