# Checkpoint atómico del estado de ejecución: escribe un temporal y luego lo reemplaza

from __future__ import annotations

import json
import os
import pickle
from pathlib import Path
from typing import Any

import numpy as np


CHECKPOINT_DIR = Path(__file__).resolve().parent / "checkpoints"
CHECKPOINT_PATH = CHECKPOINT_DIR / "checkpoint.pkl"


def _json_path(pkl_path: Path) -> Path:
    return pkl_path.with_suffix(".json")


def summarize_state(state: dict[str, Any]) -> dict[str, Any]:
    # Resumen legible del checkpoint (sin volcar todas las matrices)        
    modelo = state.get("model") or {}
    historial = list(state.get("history") or [])
    pesos: dict[str, Any] = {}
    for nombre, arreglo in modelo.items():
        valores = np.asarray(arreglo)
        pesos[nombre] = {
            "shape": list(valores.shape),
            "min": round(float(valores.min()), 5),
            "max": round(float(valores.max()), 5),
            "mean": round(float(valores.mean()), 5),
            "muestra": [round(float(x), 5) for x in valores.ravel()[:8]],
        }
    return {
        "epoch": state.get("epoch"),
        "epocas_en_historial": len(historial),
        "primer_registro": historial[0] if historial else None,
        "ultimo_registro": historial[-1] if historial else None,
        "pesos": pesos,
        "args": state.get("args"),
    }


def save_checkpoint(state: dict[str, Any], path: Path | None = None) -> Path:
    destino = Path(path) if path is not None else CHECKPOINT_PATH
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(destino.suffix + ".tmp")

    with open(temporal, "wb") as archivo:
        pickle.dump(state, archivo, protocol=pickle.HIGHEST_PROTOCOL)
        archivo.flush()
        os.fsync(archivo.fileno())

    if destino.exists():
        anterior = destino.with_suffix(destino.suffix + ".prev")
        os.replace(destino, anterior)

    os.replace(temporal, destino)

    resumen = summarize_state(state)
    with open(_json_path(destino), "w", encoding="utf-8") as archivo:
        json.dump(resumen, archivo, indent=2, ensure_ascii=False)
        archivo.write("\n")
    return destino


def load_checkpoint(path: Path | None = None) -> dict[str, Any] | None:
    origen = Path(path) if path is not None else CHECKPOINT_PATH
    if not origen.exists():
        return None
    with open(origen, "rb") as archivo:
        return pickle.load(archivo)


def inspect_checkpoint(path: Path | None = None) -> int:
    origen = Path(path) if path is not None else CHECKPOINT_PATH
    estado = load_checkpoint(origen)
    if estado is None:
        print(f"No hay checkpoint en {origen}")
        return 1

    resumen = summarize_state(estado)
    tamaño = origen.stat().st_size
    print(f"Archivo binario : {origen}  ({tamaño} bytes)")
    print(f"Resumen JSON    : {_json_path(origen)}")
    print(f"Epoca guardada  : {resumen['epoch']}")
    print(f"Historial       : {resumen['epocas_en_historial']} epocas")
    primero = resumen["primer_registro"]
    ultimo = resumen["ultimo_registro"]
    if primero:
        print(
            f"Primera epoca   : {primero['epoch']}  "
            f"loss={primero['loss']:.4f}  accuracy={primero['acc']:.3f}"
        )
    if ultimo:
        print(
            f"Ultima epoca    : {ultimo['epoch']}  "
            f"loss={ultimo['loss']:.4f}  accuracy={ultimo['acc']:.3f}"
        )
        print("Si el entrenamiento se hubiera reiniciado, el loss volveria a ~0.47.")
    print("Pesos restaurables:")
    for nombre, info in resumen["pesos"].items():
        print(
            f"  {nombre:4s}  shape={info['shape']}  "
            f"mean={info['mean']}  muestra={info['muestra']}"
        )
    return 0


def delete_checkpoint(path: Path | None = None) -> None:
    origen = Path(path) if path is not None else CHECKPOINT_PATH
    for candidato in (
        origen,
        origen.with_suffix(origen.suffix + ".tmp"),
        origen.with_suffix(origen.suffix + ".prev"),
        _json_path(origen),
    ):
        if candidato.exists():
            candidato.unlink()
