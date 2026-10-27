"""Reads the load balancer's live status: the HAProxy stats page as CSV.

Shared by uptime_monitor.py and autoscale.py; standard library only.
"""
import csv
import io
import urllib.request

FRONTEND = "api_edge"
BACKEND = "api"


def fetch(stats_url: str, timeout: float = 5) -> list[dict[str, str]]:
    with urllib.request.urlopen(f"{stats_url};csv", timeout=timeout) as response:
        return parse(response.read().decode("utf-8"))


def parse(text: str) -> list[dict[str, str]]:
    # The header line starts with "# "
    return list(csv.DictReader(io.StringIO(text.removeprefix("# "))))


def _row(rows: list[dict[str, str]], proxy: str, name: str) -> dict[str, str]:
    return next((row for row in rows if row["pxname"] == proxy and row["svname"] == name), {})


def frontend(rows: list[dict[str, str]]) -> dict[str, str]:
    return _row(rows, FRONTEND, "FRONTEND")


def backend(rows: list[dict[str, str]]) -> dict[str, str]:
    return _row(rows, BACKEND, "BACKEND")


def instances(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """API instances Docker is running. Unused slots of the server template are
    in maintenance ("MAINT (resolution)") and left out."""
    return [
        row for row in rows
        if row["pxname"] == BACKEND
        and row["svname"] not in ("FRONTEND", "BACKEND")
        and not row["status"].startswith("MAINT")
    ]


def healthy(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    # "UP 1/2" while an instance is failing checks but not yet taken out
    return [row for row in instances(rows) if row["status"].startswith("UP")]


def number(row: dict[str, str], field: str) -> int:
    value = row.get(field, "")
    return int(value) if value.isdigit() else 0


def denied(rows: list[dict[str, str]]) -> int:
    """Requests and connections refused at the edge (rate limits and filters) since it started."""
    edge = frontend(rows)
    return number(edge, "dreq") + number(edge, "dcon")
