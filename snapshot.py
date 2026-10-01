"""On-disk format of one scrape run.

data/<stamp>/flights.csv    one row per nonstop flight
data/<stamp>/routes.csv     one row per search attempt (last row per route wins)
data/<stamp>/drops.csv      validation drop counts per route and reason
data/<stamp>/reference.json Google's cheapest single-ticket MIA-ORD fares
data/<stamp>/COMPLETE       present once every route is ok or no_service
"""
import csv
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("FLIGHT_LP_DATA", Path(__file__).parent / "data"))
FLIGHT_COLUMNS = ["origin", "dest", "carrier", "airline", "flight_number", "dep_local", "arr_local",
                  "price_usd", "is_american", "aircraft", "scraped_at"]
ROUTE_COLUMNS = ["origin", "dest", "status", "n_flights", "scraped_at"]
DROP_COLUMNS = ["origin", "dest", "reason", "count"]


def new_run_dir(stamp: str, data_dir: Path = DATA_DIR) -> Path:
    run_dir = data_dir / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def is_complete(run_dir: Path) -> bool:
    return (run_dir / "COMPLETE").exists()


def mark_complete(run_dir: Path) -> None:
    (run_dir / "COMPLETE").write_text("")


def latest_run(data_dir: Path = DATA_DIR, complete: bool = True) -> Path | None:
    """Most recent run directory that is complete (or, with complete=False, not yet complete)."""
    if not data_dir.exists():
        return None
    runs = sorted(p for p in data_dir.iterdir() if p.is_dir() and is_complete(p) == complete)
    return runs[-1] if runs else None


def append_rows(path: Path, columns: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    new_file = not path.exists()
    with path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        if new_file:
            writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def route_status(run_dir: Path) -> dict[tuple[str, str], str]:
    status = {}
    for row in read_rows(run_dir / "routes.csv"):
        status[(row["origin"], row["dest"])] = row["status"]
    return status
