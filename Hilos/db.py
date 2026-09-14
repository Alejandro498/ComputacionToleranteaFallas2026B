# SQLite de la tienda: una conexión por hilo y pedidos en transacción.

from __future__ import annotations

import sqlite3
from pathlib import Path

PRODUCTOS_INICIALES = [
    (1, "Mouse", 20),
    (2, "Teclado", 15),
    (3, "Monitor", 8),
    (4, "Audifonos", 12),
]


def connect(db_path: Path) -> sqlite3.Connection:
    """Cada hilo debe llamar esto por su cuenta. No se comparte la conexión."""
    conn = sqlite3.connect(db_path, timeout=1.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    for extra in (db_path.with_suffix(".db-wal"), db_path.with_suffix(".db-shm")):
        if extra.exists():
            extra.unlink()

    conn = connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE products (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                stock INTEGER NOT NULL
            );
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                product_id INTEGER NOT NULL,
                qty INTEGER NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                worker TEXT,
                error TEXT,
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            """
        )
        conn.executemany(
            "INSERT INTO products (id, name, stock) VALUES (?, ?, ?)",
            PRODUCTOS_INICIALES,
        )
        conn.commit()
    finally:
        conn.close()


def insert_pending(conn: sqlite3.Connection, product_id: int, qty: int) -> int:
    cur = conn.execute(
        "INSERT INTO orders (product_id, qty, status) VALUES (?, ?, 'pending')",
        (product_id, qty),
    )
    conn.commit()
    return int(cur.lastrowid)


def mark_order(
    conn: sqlite3.Connection,
    order_id: int,
    status: str,
    attempts: int,
    worker: str,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE orders
        SET status = ?, attempts = ?, worker = ?, error = ?
        WHERE id = ?
        """,
        (status, attempts, worker, error, order_id),
    )
    conn.commit()


def fulfill_safe(conn: sqlite3.Connection, product_id: int, qty: int) -> str:
    """Baja el stock en una sola transacción. No deja el inventario a medias."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
            (qty, product_id, qty),
        )
        if cur.rowcount == 0:
            conn.execute("ROLLBACK")
            return "sin_stock"
        conn.execute("COMMIT")
        return "ok"
    except sqlite3.Error:
        conn.execute("ROLLBACK")
        raise


def fulfill_unsafe(conn: sqlite3.Connection, product_id: int, qty: int, race_delay: float) -> str:
    """Lee el stock, espera y luego escribe. Dos hilos pueden pisarse el valor."""
    import time

    row = conn.execute(
        "SELECT stock FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()
    stock = int(row["stock"])
    time.sleep(race_delay)
    if stock < qty:
        return "sin_stock"
    conn.execute(
        "UPDATE products SET stock = ? WHERE id = ?",
        (stock - qty, product_id),
    )
    conn.commit()
    return "ok"


def stock_of(conn: sqlite3.Connection, product_id: int) -> int:
    row = conn.execute(
        "SELECT stock FROM products WHERE id = ?",
        (product_id,),
    ).fetchone()
    return int(row["stock"])


def resumen(conn: sqlite3.Connection) -> dict:
    pedidos = list(conn.execute("SELECT * FROM orders ORDER BY id"))
    productos = list(conn.execute("SELECT * FROM products ORDER BY id"))
    vendidos = {
        row["product_id"]: row["total"]
        for row in conn.execute(
            """
            SELECT product_id, COALESCE(SUM(qty), 0) AS total
            FROM orders
            WHERE status = 'ok'
            GROUP BY product_id
            """
        )
    }
    return {
        "pedidos": pedidos,
        "productos": productos,
        "vendidos": vendidos,
        "ok": _count(pedidos, "ok"),
        "sin_stock": _count(pedidos, "sin_stock"),
        "failed": _count(pedidos, "failed"),
        "pending": _count(pedidos, "pending"),
    }


def _count(pedidos: list[sqlite3.Row], status: str) -> int:
    return sum(1 for p in pedidos if p["status"] == status)
