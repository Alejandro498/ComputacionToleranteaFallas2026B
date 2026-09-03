# Dataset 2D de dos lunas (equivalente sencillo a sklearn.datasets.make_moons)

from __future__ import annotations

import numpy as np


def make_moons(n_samples: int = 400, noise: float = 0.15, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    # Devuelve puntos (x, y) y etiquetas 0/1 para dos lunas entrelazadas
    n_samples = int(n_samples)
    if n_samples < 2:
        raise ValueError("n_samples debe ser al menos 2")

    n_positive = n_samples // 2
    n_negative = n_samples - n_positive
    rng = np.random.default_rng(seed)

    theta_neg = rng.uniform(0.0, np.pi, n_negative)
    theta_pos = rng.uniform(0.0, np.pi, n_positive)

    luna_0 = np.column_stack((np.cos(theta_neg), np.sin(theta_neg)))
    luna_1 = np.column_stack((1.0 - np.cos(theta_pos), 1.0 - np.sin(theta_pos) - 0.5))

    X = np.vstack((luna_0, luna_1)).astype(np.float64)
    y = np.concatenate((np.zeros(n_negative), np.ones(n_positive))).astype(np.float64)
    X += rng.normal(0.0, noise, X.shape)

    orden = rng.permutation(n_samples)
    return X[orden], y[orden]
