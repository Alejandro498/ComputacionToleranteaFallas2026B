"""
Parte 1 — Getting Started with Prefect (PyData Denver).

ETL del tutorial (extract → transform → load) portado a Prefect 3.
Fuente: API de quejas del CFPB. Si la API bloquea (403), se usa una
muestra local con la misma forma para poder correr el flow.
"""

from __future__ import annotations

import sqlite3
from collections import namedtuple
from contextlib import closing
from pathlib import Path

import requests
from prefect import flow, task

CFPB_URL = (
    "https://www.consumerfinance.gov/data-research/"
    "consumer-complaints/search/api/v1/"
)
DB_PATH = Path("salida/cfpbcomplaints.db")

# Muestra con la misma forma que hits.hits de la API (por si responde 403).
SAMPLE_HITS = [
    {
        "_source": {
            "date_received": "2024-01-15",
            "state": "CA",
            "product": "Credit card",
            "company": "Example Bank",
            "complaint_what_happened": "Charged a fee I did not authorize.",
        }
    },
    {
        "_source": {
            "date_received": "2024-02-03",
            "state": "TX",
            "product": "Mortgage",
            "company": "Example Mortgage Co",
            "complaint_what_happened": "Loan servicing error on payment.",
        }
    },
    {
        "_source": {
            "date_received": "2024-03-20",
            "state": "NY",
            "product": "Checking or savings account",
            "company": "Example Credit Union",
            "complaint_what_happened": "Account closed without notice.",
        }
    },
]


## extract
@task(retries=2, retry_delay_seconds=2, log_prints=True)
def get_complaint_data():
    print(f"GET {CFPB_URL}?size=10")
    try:
        r = requests.get(
            CFPB_URL,
            params={"size": 10},
            timeout=30,
            headers={
                "User-Agent": "WorkflowManagers-Prefect/1.0",
                "Accept": "application/json",
            },
        )
        r.raise_for_status()
        response_json = r.json()
        hits = response_json["hits"]["hits"]
        print(f"API OK: {len(hits)} quejas")
        return hits
    except (requests.RequestException, ValueError, KeyError) as exc:
        print(f"API no disponible ({exc}); usando muestra local")
        return SAMPLE_HITS


## transform
@task(log_prints=True)
def parse_complaint_data(raw):
    complaints = []
    Complaint = namedtuple(
        "Complaint",
        ["date_received", "state", "product", "company", "complaint_what_happened"],
    )
    for row in raw:
        source = row.get("_source", {})
        # El tutorial escribe date_recieved (typo); la API usa date_received.
        this_complaint = Complaint(
            date_received=source.get("date_received") or source.get("date_recieved"),
            state=source.get("state"),
            product=source.get("product"),
            company=source.get("company"),
            complaint_what_happened=source.get("complaint_what_happened"),
        )
        complaints.append(this_complaint)
    print(f"Parseadas {len(complaints)} quejas")
    for c in complaints[:3]:
        print(f"  - {c.state} | {c.product} | {c.company}")
    return complaints


## load
@task(log_prints=True)
def store_complaints(parsed):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    create_script = (
        "CREATE TABLE IF NOT EXISTS complaint ("
        "timestamp TEXT, state TEXT, product TEXT, "
        "company TEXT, complaint_what_happened TEXT)"
    )
    insert_cmd = "INSERT INTO complaint VALUES (?, ?, ?, ?, ?)"

    with closing(sqlite3.connect(DB_PATH)) as conn:
        with closing(conn.cursor()) as cursor:
            cursor.executescript(create_script)
            cursor.executemany(insert_cmd, parsed)
            conn.commit()
            n = cursor.execute("SELECT COUNT(*) FROM complaint").fetchone()[0]

    print(f"Guardadas {n} filas en {DB_PATH}")
    return str(DB_PATH)


@flow(name="my etl flow", log_prints=True)
def my_etl_flow():
    raw = get_complaint_data()
    parsed = parse_complaint_data(raw)
    return store_complaints(parsed)


if __name__ == "__main__":
    my_etl_flow()
