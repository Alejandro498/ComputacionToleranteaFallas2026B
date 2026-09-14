# Tienda concurrente: el hilo principal encola pedidos y varios workers los procesan.

from __future__ import annotations

import argparse
import logging
import random
import sys
import threading
import time
from pathlib import Path
from queue import Queue

from db import PRODUCTOS_INICIALES, connect, init_db, insert_pending, resumen
from workers import Pedido, Stats, start_workers

DB_PATH = Path(__file__).resolve().parent / "pedidos.db"
INICIAL = {pid: stock for pid, _nombre, stock in PRODUCTOS_INICIALES}
NOMBRES = {pid: nombre for pid, nombre, _stock in PRODUCTOS_INICIALES}

log = logging.getLogger("hilos")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pedidos concurrentes con hilos y SQLite."
    )
    parser.add_argument("--workers", type=int, default=4, help="Hilos worker (cajeros)")
    parser.add_argument("--orders", type=int, default=24, help="Pedidos a procesar")
    parser.add_argument(
        "--fail-rate",
        type=float,
        default=0.30,
        help="Probabilidad de falla transitoria por intento (0 a 1)",
    )
    parser.add_argument("--max-attempts", type=int, default=3, help="Reintentos por pedido")
    parser.add_argument(
        "--unsafe",
        action="store_true",
        help="Leer y escribir el stock sin transaccion (se pierden actualizaciones)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.15,
        help="Pausa al encolar y, en --unsafe, ventana para la condicion de carrera",
    )
    parser.add_argument("--seed", type=int, default=42, help="Semilla de pedidos y fallas")
    return parser.parse_args()


def configurar_log() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  [%(threadName)s]  %(message)s",
        datefmt="%H:%M:%S",
    )


def imprimir_resumen(stats: Stats, n_workers: int, unsafe: bool) -> None:
    conn = connect(DB_PATH)
    try:
        r = resumen(conn)
    finally:
        conn.close()

    print()
    print("=" * 62)
    print("Resumen")
    print("=" * 62)
    print(f"Hilo principal     {threading.main_thread().name}  id={threading.get_ident()}")
    print(f"Hilos worker       {n_workers}")
    print(f"Modo               {'UNSAFE (sin transaccion)' if unsafe else 'SAFE (transaccion)'}")
    print(f"Pedidos OK         {r['ok']}")
    print(f"Sin stock          {r['sin_stock']}")
    print(f"Fallidos           {r['failed']}")
    print(f"Reintentos         {stats.retries}")
    print()
    print(f"{'Producto':<12} {'inicial':>8} {'actual':>8} {'vendidos':>10}  invariante")
    print("-" * 62)

    coherente = True
    for prod in r["productos"]:
        pid = prod["id"]
        inicial = INICIAL[pid]
        actual = prod["stock"]
        vendidos = int(r["vendidos"].get(pid, 0))
        ok = inicial == actual + vendidos
        coherente = coherente and ok
        marca = "OK" if ok else "ROTO (se perdio una venta)"
        print(
            f"{NOMBRES[pid]:<12} {inicial:>8} {actual:>8} {vendidos:>10}  {marca}"
        )

    print("-" * 62)
    if unsafe:
        print(
            "En modo unsafe el invariante suele romperse: dos hilos leen el mismo "
            "stock y el segundo pisa la baja del primero."
        )
    elif coherente:
        print(
            "Invariante OK: inicial = stock actual + vendidos. "
            "Los hilos no se pisaron el inventario."
        )
    else:
        print("Invariante ROTO: algo quedo inconsistente.")
    print("=" * 62)


def main() -> int:
    args = parse_args()
    configurar_log()

    if args.workers < 1:
        print("--workers tiene que ser al menos 1", file=sys.stderr)
        return 2

    init_db(DB_PATH)
    cola: Queue[Pedido | None] = Queue()
    stats = Stats()
    rng = random.Random(args.seed)

    log.info(
        "hilo principal  id=%s  workers=%s  pedidos=%s  fail-rate=%.0f%%  %s",
        threading.get_ident(),
        args.workers,
        args.orders,
        args.fail_rate * 100,
        "UNSAFE" if args.unsafe else "SAFE",
    )

    hilos = start_workers(
        n_workers=args.workers,
        queue=cola,
        db_path=DB_PATH,
        fail_rate=0.0 if args.unsafe else args.fail_rate,
        max_attempts=args.max_attempts,
        unsafe=args.unsafe,
        race_delay=args.delay,
        stats=stats,
        seed=args.seed,
    )

    conn = connect(DB_PATH)
    try:
        for _ in range(args.orders):
            product_id = rng.choice([p[0] for p in PRODUCTOS_INICIALES])
            qty = rng.randint(1, 3)
            order_id = insert_pending(conn, product_id, qty)
            cola.put(Pedido(id=order_id, product_id=product_id, qty=qty))
            log.info(
                "encola pedido #%s  %s x%s",
                order_id,
                NOMBRES[product_id],
                qty,
            )
            # En --unsafe no se pausa al encolar: los workers chocan sobre el mismo stock.
            if args.delay > 0 and not args.unsafe:
                time.sleep(args.delay)
    finally:
        conn.close()

    for _ in hilos:
        cola.put(None)

    cola.join()
    for hilo in hilos:
        hilo.join()

    imprimir_resumen(stats, args.workers, args.unsafe)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
