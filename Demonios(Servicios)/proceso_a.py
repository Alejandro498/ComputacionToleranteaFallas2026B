# Proceso A: servicio de bitacora del sensor de un cuarto de servidores.
# Corre en bucle. Si el demonio supervisor lo relanza, continua la secuencia.

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ / "datos"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Servicio principal (proceso A): registra la temperatura del cuarto."
    )
    parser.add_argument(
        "--intervalo",
        type=float,
        default=1.0,
        help="Segundos entre lecturas",
    )
    parser.add_argument(
        "--fallar-tras",
        type=int,
        default=0,
        help="Tras N lecturas lanza una excepcion no capturada (0 = no fallar)",
    )
    parser.add_argument(
        "--directorio",
        type=Path,
        default=DATOS,
        help="Carpeta de la bitacora y la senal de apagado",
    )
    return parser.parse_args()


def emitir(mensaje: str) -> None:
    print(mensaje, flush=True)


def ahora() -> str:
    return datetime.now().strftime("%H:%M:%S")


def siguiente_seq(bitacora: Path) -> int:
    ultimo = 0
    if not bitacora.exists():
        return 1
    for linea in bitacora.read_text(encoding="utf-8").splitlines():
        if not linea or linea.startswith("#"):
            continue
        try:
            ultimo = int(linea.split("\t", 1)[0])
        except ValueError:
            continue
    return ultimo + 1


def marcar(bitacora: Path, texto: str) -> None:
    with bitacora.open("a", encoding="utf-8") as archivo:
        archivo.write(texto + "\n")
        archivo.flush()


def leer_sensor(seq: int) -> float:
    # Simula un sensor: 22 C de base y una oscilacion lenta.
    return 22.0 + 3.0 * math.sin(seq / 5.0)


def esperar(segundos: float, detener: Path) -> bool:
    """Duerme en tramos cortos. Devuelve True si aparecio la senal de apagado."""
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if detener.exists():
            return True
        time.sleep(min(0.1, limite - time.monotonic()))
    return detener.exists()


def apagado_ordenado(bitacora: Path, detener: Path, pidfile: Path, pid: int) -> int:
    marcar(bitacora, f"# apagado ordenado pid={pid} {ahora()}")
    emitir(f"[servicio {pid}] apagado ordenado")
    detener.unlink(missing_ok=True)
    pidfile.unlink(missing_ok=True)
    return 0


def main() -> int:
    args = parse_args()
    if args.intervalo <= 0:
        print("--intervalo tiene que ser mayor que 0", file=sys.stderr)
        return 2
    if args.fallar_tras < 0:
        print("--fallar-tras no puede ser negativo", file=sys.stderr)
        return 2

    datos: Path = args.directorio
    datos.mkdir(parents=True, exist_ok=True)
    bitacora = datos / "bitacora.log"
    detener = datos / "detener"
    pidfile = datos / "servicio.pid"
    pid = os.getpid()
    pidfile.write_text(str(pid), encoding="utf-8")

    seq = siguiente_seq(bitacora)
    marcar(bitacora, f"# arranque pid={pid} seq={seq} {ahora()}")
    emitir(f"[servicio {pid}] arranca (siguiente seq={seq})")

    tomadas = 0
    try:
        while True:
            if detener.exists():
                return apagado_ordenado(bitacora, detener, pidfile, pid)

            temp = leer_sensor(seq)
            linea = f"{seq}\t{ahora()}\tpid={pid}\ttemp={temp:.2f}"
            marcar(bitacora, linea)
            emitir(f"[servicio {pid}] {linea.replace(chr(9), ' ')}")
            seq += 1
            tomadas += 1

            if args.fallar_tras and tomadas >= args.fallar_tras:
                marcar(
                    bitacora,
                    f"# FALLA inesperada pid={pid} tras {tomadas} lecturas {ahora()}",
                )
                emitir(
                    f"[servicio {pid}] *** Falla inesperada: "
                    "excepcion no capturada en el sensor ***"
                )
                # No se captura: el proceso muere con codigo distinto de 0.
                raise RuntimeError("lectura de sensor invalida")

            if esperar(args.intervalo, detener):
                return apagado_ordenado(bitacora, detener, pidfile, pid)
    except KeyboardInterrupt:
        return apagado_ordenado(bitacora, detener, pidfile, pid)


if __name__ == "__main__":
    sys.exit(main())
