"""
Parte 2 — Mismo ETL del tutorial, modificado para jsonplaceholder.cypress.io.

extract → transform → load:
  GET /posts  →  namedtuple Post  →  SQLite (salida/posts_cypress.db)
"""

from __future__ import annotations

import sqlite3
from collections import namedtuple
from contextlib import closing
from pathlib import Path

import requests
from prefect import flow, task

BASE = "https://jsonplaceholder.cypress.io"
HEADERS = {
    "User-Agent": "WorkflowManagers-Prefect/1.0",
    "Accept": "application/json",
}
DB_PATH = Path("salida/posts_cypress.db")


## extract
@task(retries=3, retry_delay_seconds=2, log_prints=True)
def get_post_data():
    url = f"{BASE}/posts"
    print(f"GET {url}")
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    posts = r.json()
    print(f"API OK: {len(posts)} posts")
    return posts


## transform
@task(log_prints=True)
def parse_post_data(raw):
    posts = []
    Post = namedtuple("Post", ["user_id", "post_id", "title", "body"])
    for row in raw:
        posts.append(
            Post(
                user_id=row.get("userId"),
                post_id=row.get("id"),
                title=row.get("title"),
                body=row.get("body"),
            )
        )
    print(f"Parseados {len(posts)} posts")
    for p in posts[:3]:
        print(f"  - #{p.post_id} (user {p.user_id}): {p.title[:40]}...")
    return posts


## load
@task(log_prints=True)
def store_posts(parsed):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()

    create_script = (
        "CREATE TABLE IF NOT EXISTS post ("
        "user_id INTEGER, post_id INTEGER, title TEXT, body TEXT)"
    )
    insert_cmd = "INSERT INTO post VALUES (?, ?, ?, ?)"

    with closing(sqlite3.connect(DB_PATH)) as conn:
        with closing(conn.cursor()) as cursor:
            cursor.executescript(create_script)
            cursor.executemany(insert_cmd, parsed)
            conn.commit()
            n = cursor.execute("SELECT COUNT(*) FROM post").fetchone()[0]
            users = cursor.execute(
                "SELECT COUNT(DISTINCT user_id) FROM post"
            ).fetchone()[0]

    print(f"Guardadas {n} filas ({users} usuarios) en {DB_PATH}")
    return str(DB_PATH)


@flow(name="cypress posts etl", log_prints=True)
def cypress_posts_etl():
    raw = get_post_data()
    parsed = parse_post_data(raw)
    return store_posts(parsed)


if __name__ == "__main__":
    cypress_posts_etl()
