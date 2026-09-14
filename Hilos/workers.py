# Hilos worker: toman pedidos de la cola, hablan con SQLite y reintentan si fallan.

from __future__ import annotations

import logging
import random
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from queue import Queue

from db import connect, fulfill_safe, fulfill_unsafe, mark_order, stock_of

log = logging.getLogger("hilos")


@dataclass
class Pedido:
    id: int
    product_id: int
    qty: int


@dataclass
class Stats:
    retries: int = 0
    lock = threading.Lock()

    def add_retry(self) -> None:
        with self.lock:
            self.retries += 1


def worker_loop(
    queue: Queue[Pedido | None],
    db_path: Path,
    fail_rate: float,
    max_attempts: int,
    unsafe: bool,
    race_delay: float,
    stats: Stats,
    rng: random.Random,
) -> None:
    nombre = threading.current_thread().name
    nativo = threading.get_ident()
    conn = connect(db_path)
    log.info("arranca  id nativo=%s  conexion propia a %s", nativo, db_path.name)

    try:
        while True:
            pedido = queue.get()
            try:
                if pedido is None:
                    log.info("recibe senal de corte, cierra")
                    return
                _procesar(
                    conn,
                    pedido,
                    nombre,
                    fail_rate,
                    max_attempts,
                    unsafe,
                    race_delay,
                    stats,
                    rng,
                )
            finally:
                queue.task_done()
    finally:
        conn.close()
        log.info("termina  conexion cerrada")


def _procesar(
    conn: sqlite3.Connection,
    pedido: Pedido,
    worker: str,
    fail_rate: float,
    max_attempts: int,
    unsafe: bool,
    race_delay: float,
    stats: Stats,
    rng: random.Random,
) -> None:
    ultimo_error = None

    for intento in range(1, max_attempts + 1):
        try:
            if fail_rate > 0 and rng.random() < fail_rate:
                raise RuntimeError("falla transitoria simulada")

            if unsafe:
                resultado = fulfill_unsafe(conn, pedido.product_id, pedido.qty, race_delay)
            else:
                resultado = fulfill_safe(conn, pedido.product_id, pedido.qty)

            stock = stock_of(conn, pedido.product_id)
            mark_order(conn, pedido.id, resultado, intento, worker)
            if resultado == "ok":
                log.info(
                    "pedido #%s qty=%s  OK  intento=%s/%s  stock_restante=%s",
                    pedido.id,
                    pedido.qty,
                    intento,
                    max_attempts,
                    stock,
                )
            else:
                log.info(
                    "pedido #%s qty=%s  SIN STOCK  intento=%s/%s  stock=%s",
                    pedido.id,
                    pedido.qty,
                    intento,
                    max_attempts,
                    stock,
                )
            return

        except (RuntimeError, sqlite3.OperationalError, sqlite3.DatabaseError) as exc:
            ultimo_error = str(exc)
            log.warning(
                "pedido #%s  intento %s/%s  ERROR: %s",
                pedido.id,
                intento,
                max_attempts,
                ultimo_error,
            )
            if intento < max_attempts:
                stats.add_retry()
                espera = 0.25 * intento
                log.info("pedido #%s  reintenta en %.2fs", pedido.id, espera)
                time.sleep(espera)

    mark_order(conn, pedido.id, "failed", max_attempts, worker, ultimo_error)
    log.error(
        "pedido #%s  FALLIDO despues de %s intentos (%s)",
        pedido.id,
        max_attempts,
        ultimo_error,
    )


def start_workers(
    n_workers: int,
    queue: Queue[Pedido | None],
    db_path: Path,
    fail_rate: float,
    max_attempts: int,
    unsafe: bool,
    race_delay: float,
    stats: Stats,
    seed: int,
) -> list[threading.Thread]:
    """Crea y arranca los hilos. Cada uno es un cajero con su propia conexion."""
    hilos: list[threading.Thread] = []
    for i in range(n_workers):
        rng = random.Random(seed + i + 1)
        hilo = threading.Thread(
            target=worker_loop,
            name=f"worker-{i + 1}",
            args=(
                queue,
                db_path,
                fail_rate,
                max_attempts,
                unsafe,
                race_delay,
                stats,
                rng,
            ),
        )
        hilo.start()
        hilos.append(hilo)
    return hilos
