"""The 22 airports in the network: MIA (origin), ORD (destination), and 20 connection candidates."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Airport:
    code: str
    city: str
    lat: float
    lon: float
    tz: str


ORIGIN = "MIA"
DEST = "ORD"
TRIP_DATE = "2026-11-20"

# Connection candidates: a mix of large hubs and mid-size airports. Edit freely.
HUBS = [
    "ATL", "CLT", "DFW", "DCA", "PHL", "DTW", "IAH", "EWR",
    "BNA", "RDU", "CVG", "CLE", "CMH", "IND", "PIT", "MSY", "JAX", "MEM", "STL", "SAV",
]

_ET = "America/New_York"
_CT = "America/Chicago"

AIRPORTS: dict[str, Airport] = {a.code: a for a in [
    Airport("MIA", "Miami", 25.795, -80.290, _ET),
    Airport("ORD", "Chicago O'Hare", 41.974, -87.907, _CT),
    Airport("ATL", "Atlanta", 33.640, -84.427, _ET),
    Airport("CLT", "Charlotte", 35.214, -80.943, _ET),
    Airport("DFW", "Dallas-Fort Worth", 32.900, -97.040, _CT),
    Airport("DCA", "Washington National", 38.852, -77.038, _ET),
    Airport("PHL", "Philadelphia", 39.874, -75.243, _ET),
    Airport("DTW", "Detroit", 42.212, -83.353, "America/Detroit"),
    Airport("IAH", "Houston", 29.990, -95.337, _CT),
    Airport("EWR", "Newark", 40.690, -74.174, _ET),
    Airport("BNA", "Nashville", 36.124, -86.678, _CT),
    Airport("RDU", "Raleigh-Durham", 35.878, -78.787, _ET),
    Airport("CVG", "Cincinnati", 39.049, -84.668, _ET),
    Airport("CLE", "Cleveland", 41.412, -81.850, _ET),
    Airport("CMH", "Columbus", 39.998, -82.892, _ET),
    Airport("IND", "Indianapolis", 39.717, -86.294, "America/Indiana/Indianapolis"),
    Airport("PIT", "Pittsburgh", 40.492, -80.233, _ET),
    Airport("MSY", "New Orleans", 29.993, -90.258, _CT),
    Airport("JAX", "Jacksonville", 30.494, -81.688, _ET),
    Airport("MEM", "Memphis", 35.042, -89.977, _CT),
    Airport("STL", "St. Louis", 38.749, -90.370, _CT),
    Airport("SAV", "Savannah", 32.128, -81.202, _ET),
]}


def search_routes() -> list[tuple[str, str]]:
    """Every directed pair worth searching: 21 origins x 21 destinations minus 20 self-pairs = 421."""
    origins = [ORIGIN] + HUBS
    dests = HUBS + [DEST]
    return [(o, d) for o in origins for d in dests if o != d]
