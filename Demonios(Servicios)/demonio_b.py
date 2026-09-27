# Demonio B: supervisor. Lanza el proceso A y lo reinicia si muere inesperadamente.
# Un codigo de salida 0 es un apagado ordenado: no se relanza.

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
DATOS = RAIZ / "datos"
SERVICIO = RAIZ / "proceso_a.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Demonio monitor (proceso B): reinicia el servicio si muere."
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Falla dos veces, relanza, y despues hace un apagado ordenado",
    )
    parser.add_argument(
        "--intervalo",
        type=float,
        default=1.0,
        help="Segundos entre lecturas del servicio",
    )
    parser.add_argument(
        "--fallar-tras",
        type=int,
        default=0,
        help="El servicio muere tras N lecturas en cada vida (0 = no fallar)",
    )
    parser.add_argument(
        "--max-reinicios",
        type=int,
        default=5,
        help="Tope de reinicios ante falla. Despues el demonio se detiene",
    )
    parser.add_argument(
        "--muestras-estables",
        type=int,
        default=3,
        help="En --demo, lecturas de la vida estable antes del apagado ordenado",
    )
    parser.add_argument(
        "--directorio",
        type=Path,
        default=DATOS,
        help="Carpeta compartida con el servicio",
    )
    return parser.parse_args()


def ahora() -> str:
    return datetime.now().strftime("%H:%M:%S")


def emitir(mensaje: str, registro: Path) -> None:
    linea = f"[demonio {ahora()}] {mensaje}"
    print(linea, flush=True)
    with registro.open("a", encoding="utf-8") as archivo:
        archivo.write(linea + "\n")


def limpiar(datos: Path) -> None:
    datos.mkdir(parents=True, exist_ok=True)
    for nombre in ("bitacora.log", "supervisor.log", "servicio.pid", "detener"):
        ruta = datos / nombre
        if ruta.exists():
            ruta.unlink()


def contar_lecturas(bitacora: Path) -> int:
    if not bitacora.exists():
        return 0
    total = 0
    for linea in bitacora.read_text(encoding="utf-8").splitlines():
        if not linea or linea.startswith("#"):
            continue
        total += 1
    return total


def lanzar(datos: Path, intervalo: float, fallar_tras: int) -> subprocess.Popen:
    comando = [
        sys.executable,
        str(SERVICIO),
        "--intervalo",
        str(intervalo),
        "--fallar-tras",
        str(fallar_tras),
        "--directorio",
        str(datos),
    ]
    return subprocess.Popen(comando, cwd=str(RAIZ))


def pedir_apagado(detener: Path) -> None:
    detener.write_text("apagado\n", encoding="utf-8")


def vigilar(proc: subprocess.Popen, detener_si=None, detener: Path | None = None) -> int:
    pedido = False
    while proc.poll() is None:
        if detener_si is not None and not pedido and detener_si():
            if detener is not None:
                pedir_apagado(detener)
            pedido = True
        time.sleep(0.1)
    return int(proc.returncode)


def main() -> int:
    args = parse_args()
    if args.max_reinicios < 0:
        print("--max-reinicios no puede ser negativo", file=sys.stderr)
        return 2
    if args.intervalo <= 0:
        print("--intervalo tiene que ser mayor que 0", file=sys.stderr)
        return 2

    datos: Path = args.directorio
    if args.demo:
        limpiar(datos)
        args.intervalo = 0.4
        args.fallar_tras = 3
        args.max_reinicios = 2
    else:
        datos.mkdir(parents=True, exist_ok=True)
        senal = datos / "detener"
        if senal.exists():
            senal.unlink()

    registro = datos / "supervisor.log"
    bitacora = datos / "bitacora.log"
    detener = datos / "detener"

    emitir("supervisor en marcha", registro)
    vida = 0
    reinicios = 0
    proc: subprocess.Popen | None = None

    try:
        while True:
            vida += 1
            # En la demo, las primeras vidas fallan; la ultima es estable.
            fallar = args.fallar_tras
            if args.demo and vida > args.max_reinicios:
                fallar = 0

            antes = contar_lecturas(bitacora)
            proc = lanzar(datos, args.intervalo, fallar)
            emitir(f"lanza servicio vida={vida} pid={proc.pid} fallar_tras={fallar}", registro)

            def ya_hay_muestras(
                meta: int = antes + args.muestras_estables,
                ruta: Path = bitacora,
            ) -> bool:
                return contar_lecturas(ruta) >= meta

            cortar = ya_hay_muestras if (args.demo and fallar == 0) else None
            codigo = vigilar(proc, detener_si=cortar, detener=detener)
            proc = None

            if codigo == 0:
                emitir("apagado ordenado (codigo 0). No se reinicia.", registro)
                break

            if reinicios >= args.max_reinicios:
                emitir(
                    f"el servicio murio (codigo {codigo}). "
                    f"Ya use los {args.max_reinicios} reinicios permitidos. "
                    "Me detengo para no ciclar si la falla es permanente.",
                    registro,
                )
                return 1

            reinicios += 1
            emitir(
                f"el servicio murio (codigo {codigo}). Reinicio {reinicios}/{args.max_reinicios}.",
                registro,
            )
            time.sleep(0.3)
    except KeyboardInterrupt:
        emitir("interrupcion. Pido apagado ordenado del servicio.", registro)
        if proc is not None and proc.poll() is None:
            pedir_apagado(detener)
            try:
                codigo = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.terminate()
                codigo = proc.wait(timeout=5)
            if codigo == 0:
                emitir("el servicio termino en orden. No se reinicia.", registro)
            else:
                emitir(f"el servicio termino con codigo {codigo}.", registro)
        elif proc is not None and proc.returncode == 0:
            emitir("el servicio termino en orden. No se reinicia.", registro)
        return 0

    if args.demo:
        emitir("bitacora resultante:", registro)
        if bitacora.exists():
            for linea in bitacora.read_text(encoding="utf-8").splitlines():
                print(f"    {linea}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
