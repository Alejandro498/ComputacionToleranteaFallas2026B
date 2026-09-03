# Entrena el clasificador 2D, guarda checkpoints y puede reanudar tras una falla

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from checkpoint import (
    CHECKPOINT_PATH,
    delete_checkpoint,
    inspect_checkpoint,
    load_checkpoint,
    save_checkpoint,
)
from data import make_moons
from model import MLP, accuracy, binary_cross_entropy

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
LOSS_PLOT = ARTIFACTS_DIR / "loss.png"
BOUNDARY_PLOT = ARTIFACTS_DIR / "boundary.png"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clasificador 2D con checkpointing del estado de ejecución."
    )
    parser.add_argument("--epochs", type=int, default=150, help="Épocas totales de entrenamiento")
    parser.add_argument("--checkpoint-every", type=int, default=10, help="Guardar cada N épocas")
    parser.add_argument("--crash-at", type=int, default=None, help="Simular una falla al terminar esta época")
    parser.add_argument("--reset", action="store_true", help="Borrar checkpoint y empezar de cero")
    parser.add_argument(
        "--inspect",
        action="store_true",
        help="Mostrar el contenido del checkpoint y salir",
    )
    parser.add_argument(
        "--epoch-delay",
        type=float,
        default=0.2,
        help="Pausa en segundos tras cada época (para poder usar Stop en el IDE)",
    )
    parser.add_argument("--hidden", type=int, default=16, help="Neuronas de la capa oculta")
    parser.add_argument("--lr", type=float, default=0.15, help="Tasa de aprendizaje")
    parser.add_argument("--momentum", type=float, default=0.9, help="Momentum del optimizador")
    parser.add_argument("--batch-size", type=int, default=32, help="Tamaño de mini-lote")
    parser.add_argument("--n-samples", type=int, default=400, help="Puntos del dataset")
    parser.add_argument("--seed", type=int, default=42, help="Semilla para datos y pesos iniciales")
    return parser.parse_args()


def train_epoch(
    model: MLP,
    X: np.ndarray,
    y: np.ndarray,
    rng: np.random.Generator,
    lr: float,
    momentum: float,
    batch_size: int,
) -> tuple[float, float]:
    n = len(X)
    orden = rng.permutation(n)
    loss_acumulada = 0.0

    for inicio in range(0, n, batch_size):
        lote = orden[inicio : inicio + batch_size]
        xb, yb = X[lote], y[lote]
        pred = model.forward(xb)
        loss_acumulada += binary_cross_entropy(pred, yb) * len(lote)
        model.backward(xb, yb, lr=lr, momentum=momentum)

    pred_todo = model.forward(X)
    return loss_acumulada / n, accuracy(pred_todo, y)


def plot_loss(historial: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    epochs = [fila["epoch"] for fila in historial]
    losses = [fila["loss"] for fila in historial]
    plt.figure(figsize=(7, 4))
    plt.plot(epochs, losses, color="#1f77b4")
    plt.xlabel("Epoca")
    plt.ylabel("Loss (error)")
    plt.title("Evolucion del error")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()


def plot_boundary(model: MLP, X: np.ndarray, y: np.ndarray, path: Path, epoch: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    margen = 0.35
    x_min, x_max = X[:, 0].min() - margen, X[:, 0].max() + margen
    y_min, y_max = X[:, 1].min() - margen, X[:, 1].max() + margen
    xx, yy = np.meshgrid(np.linspace(x_min, x_max, 250), np.linspace(y_min, y_max, 250))
    grilla = np.column_stack((xx.ravel(), yy.ravel()))
    zz = model.forward(grilla).reshape(xx.shape)

    plt.figure(figsize=(6.5, 5.5))
    plt.contourf(xx, yy, zz, levels=[0.0, 0.5, 1.0], colors=["#9ecae1", "#fdae6b"], alpha=0.85)
    plt.contour(xx, yy, zz, levels=[0.5], colors="black", linewidths=1.2)
    plt.scatter(X[y == 0, 0], X[y == 0, 1], c="#3182bd", edgecolors="white", s=22, label="clase 0")
    plt.scatter(X[y == 1, 0], X[y == 1, 1], c="#e6550d", edgecolors="white", s=22, label="clase 1")
    plt.title(f"Frontera de decision (epoca {epoch})")
    plt.legend(loc="upper right")
    plt.tight_layout()
    plt.savefig(path, dpi=120)
    plt.close()


def snapshot(model: MLP, rng: np.random.Generator, epoch: int, historial: list[dict], args: argparse.Namespace) -> dict:
    return {
        "epoch": epoch,
        "model": model.get_state(),
        "rng": rng.bit_generator.state,
        "history": historial,
        "args": {
            "hidden": args.hidden,
            "lr": args.lr,
            "momentum": args.momentum,
            "batch_size": args.batch_size,
            "n_samples": args.n_samples,
            "seed": args.seed,
        },
    }


def persist(
    model: MLP,
    rng: np.random.Generator,
    epoch: int,
    historial: list[dict],
    args: argparse.Namespace,
    X: np.ndarray,
    y: np.ndarray,
) -> Path:
    ruta = save_checkpoint(snapshot(model, rng, epoch, historial, args))
    plot_loss(historial, LOSS_PLOT)
    plot_boundary(model, X, y, BOUNDARY_PLOT, epoch)
    print(f"  checkpoint -> {ruta}")
    return ruta


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    _configure_stdio()
    args = parse_args()
    if args.inspect:
        return inspect_checkpoint()
    if args.epochs < 1:
        print(" --epochs debe ser >= 1", file=sys.stderr)
        return 1
    if args.checkpoint_every < 1:
        print(" --checkpoint-every debe ser >= 1", file=sys.stderr)
        return 1
    if args.crash_at is not None and args.crash_at < 1:
        print(" --crash-at debe ser >= 1", file=sys.stderr)
        return 1
    if args.epoch_delay < 0:
        print(" --epoch-delay no puede ser negativo", file=sys.stderr)
        return 1

    if args.reset:
        delete_checkpoint()
        print("Checkpoint anterior borrado. Entrenamiento desde cero.")

    X, y = make_moons(n_samples=args.n_samples, noise=0.15, seed=args.seed)
    model = MLP(n_hidden=args.hidden, seed=args.seed)
    rng = np.random.default_rng(args.seed + 1)
    historial: list[dict] = []
    inicio = 1

    restaurado = None if args.reset else load_checkpoint()
    if restaurado is not None:
        guardado = restaurado.get("args", {})
        if guardado.get("hidden") not in (None, args.hidden):
            print(
                f"El checkpoint usó hidden={guardado['hidden']}; "
                "usa el mismo valor o --reset para empezar de cero.",
                file=sys.stderr,
            )
            return 1
        model.set_state(restaurado["model"])
        rng.bit_generator.state = restaurado["rng"]
        historial = list(restaurado["history"])
        inicio = int(restaurado["epoch"]) + 1
        ultimo = historial[-1] if historial else None
        print("Restaurando estado: última época completada = "
              f"{restaurado['epoch']}")
        if ultimo is not None:
            print(
                f"  ultimo loss guardado = {ultimo['loss']:.4f}  "
                f"accuracy={ultimo['acc']:.3f}"
            )
            print("  (si empezara de cero, el loss inicial seria ~0.47)")
        print(f"Se continúa desde la época {inicio} hasta {args.epochs}.")
    else:
        print("No hay checkpoint. Entrenamiento desde cero.")

    if inicio > args.epochs:
        print(f"El checkpoint ya llegó a la época {inicio - 1}; nada que entrenar.")
        plot_loss(historial, LOSS_PLOT)
        plot_boundary(model, X, y, BOUNDARY_PLOT, inicio - 1)
        print(f"Gráficas en {ARTIFACTS_DIR}")
        return 0

    try:
        for epoch in range(inicio, args.epochs + 1):
            loss, acc = train_epoch(
                model,
                X,
                y,
                rng,
                lr=args.lr,
                momentum=args.momentum,
                batch_size=args.batch_size,
            )
            historial.append({"epoch": epoch, "loss": loss, "acc": acc})
            print(f"Epoca {epoch:4d}/{args.epochs}  loss={loss:.4f}  accuracy={acc:.3f}")

            guardar = epoch % args.checkpoint_every == 0 or epoch == args.epochs
            if guardar:
                persist(model, rng, epoch, historial, args, X, y)

            if args.crash_at is not None and epoch == args.crash_at:
                if not guardar:
                    persist(model, rng, epoch, historial, args, X, y)
                print(f"*** Falla simulada al terminar la epoca {epoch} ***")
                print("Vuelve a ejecutar el mismo comando (sin --crash-at y sin --reset)")
                print("para restaurar y continuar.")
                return 2

            if args.epoch_delay:
                time.sleep(args.epoch_delay)
    except KeyboardInterrupt:
        print("\n*** Interrupcion (Stop / Ctrl+C): guardando estado actual ***")
        if not historial:
            print("No habia ninguna epoca completada; no hay nada que restaurar.")
            return 130
        epoca_guardada = int(historial[-1]["epoch"])
        persist(model, rng, epoca_guardada, historial, args, X, y)
        print(f"Estado guardado en epoca {epoca_guardada}.")
        print("Vuelve a ejecutar python train.py (sin --reset) para continuar.")
        return 130

    print("Entrenamiento terminado.")
    print(f"Checkpoint: {CHECKPOINT_PATH}")
    print(f"Gráficas:   {LOSS_PLOT}")
    print(f"            {BOUNDARY_PLOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
