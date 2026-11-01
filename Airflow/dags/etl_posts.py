"""
ETL de posts con Apache Airflow (TaskFlow API).

extraer → transformar → cargar
  GET /posts  →  conteo por usuario  →  salida/resumen_posts.json

La task extraer tiene reintentos. El primer intento de cada corrida
falla a propósito (timeout simulado) para que se vea cómo Airflow
vuelve a ejecutar solo esa task y sigue con el resto del DAG.
"""

from __future__ import annotations

import json
import os
import sys
import types
from datetime import timedelta
from pathlib import Path
from urllib.request import Request, urlopen

# Antes de importar Airflow, para que la metadata quede en esta carpeta.
os.environ.setdefault("AIRFLOW_HOME", str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "false")
os.environ.setdefault("AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION", "false")

# Airflow 3 llama os.register_at_fork al importarse. En Windows no existe.
# concurrent.futures tiene que cargarse antes: si el reemplazo ya esta puesto,
# ese modulo intenta usar un lock que aqui no tiene _at_fork_reinit.
import concurrent.futures.thread  # noqa: F401

if not hasattr(os, "register_at_fork"):
    os.register_at_fork = lambda *args, **kwargs: None  # type: ignore[attr-defined]

# fcntl y signal.setitimer solo existen en POSIX. Airflow los usa para
# lock de archivos y para el timeout al leer el DAG. En Windows no hacen falta.
if sys.platform == "win32":
    import signal

    _fcntl = types.ModuleType("fcntl")
    _fcntl.LOCK_SH = 1
    _fcntl.LOCK_EX = 2
    _fcntl.LOCK_UN = 8
    _fcntl.LOCK_NB = 4
    _fcntl.flock = lambda *_args, **_kwargs: None
    sys.modules["fcntl"] = _fcntl

    if not hasattr(signal, "SIGALRM"):
        signal.SIGALRM = 14  # type: ignore[attr-defined]
    if not hasattr(signal, "ITIMER_REAL"):
        signal.ITIMER_REAL = 0  # type: ignore[attr-defined]
    if not hasattr(signal, "setitimer"):
        signal.setitimer = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]

    # SIGALRM no es una senal valida en Windows. Si Airflow la registra,
    # no sustituimos SIGTERM: solo ignoramos ese numero.
    _signal = signal.signal

    def _signal_win(signum, handler):
        if signum == signal.SIGALRM:
            return None
        return _signal(signum, handler)

    signal.signal = _signal_win  # type: ignore[assignment]

    # socketpair no se puede heredar aqui. dag.test() corre en este proceso.
    _set_inheritable = os.set_inheritable

    def _set_inheritable_win(fd, inheritable):
        try:
            _set_inheritable(fd, inheritable)
        except OSError:
            return None

    os.set_inheritable = _set_inheritable_win  # type: ignore[assignment]

import pendulum
from airflow.sdk import dag, get_current_context, task

if sys.platform == "win32":
    import contextlib

    from airflow.sdk.execution_time.supervisor import InProcessTestSupervisor

    @contextlib.contextmanager
    def _sin_socket_de_subproceso(self):
        yield None

    InProcessTestSupervisor._setup_subprocess_socket = _sin_socket_de_subproceso  # type: ignore[method-assign]

URL = "https://jsonplaceholder.cypress.io/posts"
SALIDA = Path(__file__).resolve().parent.parent / "salida" / "resumen_posts.json"


@task(retries=2, retry_delay=timedelta(seconds=2))
def extraer() -> list[dict]:
    intento = get_current_context()["ti"].try_number
    print(f"extraer intento {intento}")
    if intento == 1:
        print("Falla transitoria simulada. Airflow reintentara solo esta task.")
        raise ConnectionError("timeout de red simulado")

    print(f"GET {URL}")
    req = Request(URL, headers={"Accept": "application/json", "User-Agent": "AirflowETL/1.0"})
    with urlopen(req, timeout=15) as resp:
        posts = json.load(resp)
    print(f"API OK: {len(posts)} posts")
    return posts


@task
def transformar(posts: list[dict]) -> dict:
    por_usuario: dict[str, int] = {}
    for post in posts:
        uid = str(post["userId"])
        por_usuario[uid] = por_usuario.get(uid, 0) + 1
    resumen = {
        "total": len(posts),
        "usuarios": len(por_usuario),
        "posts_por_usuario": por_usuario,
    }
    print(f"Parseados {resumen['total']} posts de {resumen['usuarios']} usuarios")
    return resumen


@task
def cargar(resumen: dict) -> str:
    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(resumen, indent=2), encoding="utf-8")
    print(f"Resumen guardado en {SALIDA}")
    return str(SALIDA)


@dag(
    dag_id="etl_posts",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    tags=["practica", "etl"],
)
def etl_posts():
    """Baja posts, los resume por usuario y guarda el JSON."""
    cargar(transformar(extraer()))


etl_posts()


if __name__ == "__main__":
    db_path = Path(os.environ["AIRFLOW_HOME"]) / "airflow.db"
    if not db_path.exists():
        from airflow.utils.db import upgradedb

        upgradedb()
    etl_posts().test()
