"""Time-space network: event nodes (airport, time) linked by flight arcs and zero-cost wait arcs."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from airports import AIRPORTS, DEST, ORIGIN, TRIP_DATE

TRIP_DAY = int(TRIP_DATE.split("-")[2])


@dataclass(frozen=True)
class Flight:
    id: str
    origin: str
    dest: str
    carrier: str
    airline: str
    flight_number: str
    dep: datetime  # timezone-aware, origin local
    arr: datetime  # timezone-aware, destination local
    price: int
    is_american: bool


def flight_id(flight_number: str, origin: str, dest: str, dep_local: datetime) -> str:
    return f"{flight_number.replace(' ', '')}_{origin}{dest}_{dep_local:%H%M}"


def flight_from_row(row: dict) -> Flight:
    dep = datetime.fromisoformat(row["dep_local"])
    return Flight(
        id=flight_id(row["flight_number"], row["origin"], row["dest"], dep),
        origin=row["origin"], dest=row["dest"], carrier=row["carrier"], airline=row["airline"],
        flight_number=row["flight_number"], dep=dep, arr=datetime.fromisoformat(row["arr_local"]),
        price=int(row["price_usd"]), is_american=str(row["is_american"]) == "True",
    )


@dataclass(frozen=True)
class Node:
    airport: str
    t: datetime  # UTC

    @property
    def local(self) -> datetime:
        return self.t.astimezone(ZoneInfo(AIRPORTS[self.airport].tz))

    @property
    def name(self) -> str:
        local = self.local
        suffix = "" if local.day == TRIP_DAY else f"_d{local.day:02d}"
        return f"{self.airport}_{local:%H%M}{suffix}"


@dataclass
class Network:
    flights: list[Flight]
    nodes: list[Node]
    waits: list[tuple[Node, Node]]
    tail: dict[str, Node | None]  # node a flight leaves from; None = leaves MIA
    head: dict[str, Node | None]  # node a flight feeds (arrival + MCT); None = lands at ORD
    mct: int


def build_network(flights: list[Flight], mct_min: int = 45) -> Network:
    usable = [f for f in flights if f.origin != DEST and f.dest != ORIGIN and f.origin != f.dest]
    tail, head, times = {}, {}, {}
    for f in usable:
        if f.origin == ORIGIN:
            tail[f.id] = None
        else:
            tail[f.id] = Node(f.origin, f.dep.astimezone(timezone.utc))
            times.setdefault(f.origin, set()).add(tail[f.id].t)
        if f.dest == DEST:
            head[f.id] = None
        else:
            head[f.id] = Node(f.dest, (f.arr + timedelta(minutes=mct_min)).astimezone(timezone.utc))
            times.setdefault(f.dest, set()).add(head[f.id].t)
    nodes, waits = [], []
    for airport in sorted(times):
        seq = [Node(airport, t) for t in sorted(times[airport])]
        nodes.extend(seq)
        waits.extend(zip(seq, seq[1:]))
    return Network(usable, nodes, waits, tail, head, mct_min)
