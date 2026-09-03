# Red neuronal pequeña: 2 entradas → capa oculta → 1 salida (probabilidad de clase 1)
from __future__ import annotations

import numpy as np


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))


def binary_cross_entropy(pred: np.ndarray, y: np.ndarray) -> float:
    y = y.reshape(-1, 1)
    p = np.clip(pred, 1e-7, 1.0 - 1e-7)
    return float(-np.mean(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)))


def accuracy(pred: np.ndarray, y: np.ndarray) -> float:
    clases = (pred.reshape(-1) >= 0.5).astype(np.float64)
    return float(np.mean(clases == y.reshape(-1)))


class MLP:
    # Clasificador 2D con una capa oculta y descenso por gradiente + momentum

    def __init__(self, n_hidden: int = 16, seed: int = 0) -> None:
        rng = np.random.default_rng(seed)
        escala = 0.5
        self.W1 = rng.normal(0.0, escala, (2, n_hidden))
        self.b1 = np.zeros((1, n_hidden))
        self.W2 = rng.normal(0.0, escala, (n_hidden, 1))
        self.b2 = np.zeros((1, 1))
        # Velocidades del momentum: también forman parte del estado de ejecución.
        self.vW1 = np.zeros_like(self.W1)
        self.vb1 = np.zeros_like(self.b1)
        self.vW2 = np.zeros_like(self.W2)
        self.vb2 = np.zeros_like(self.b2)

    def forward(self, X: np.ndarray) -> np.ndarray:
        self.z1 = X @ self.W1 + self.b1
        self.a1 = np.tanh(self.z1)
        self.z2 = self.a1 @ self.W2 + self.b2
        self.a2 = _sigmoid(self.z2)
        return self.a2

    def backward(self, X: np.ndarray, y: np.ndarray, lr: float, momentum: float) -> None:
        n = X.shape[0]
        y = y.reshape(-1, 1)
        dz2 = (self.a2 - y) / n
        dW2 = self.a1.T @ dz2
        db2 = np.sum(dz2, axis=0, keepdims=True)

        dz1 = (dz2 @ self.W2.T) * (1.0 - self.a1**2)
        dW1 = X.T @ dz1
        db1 = np.sum(dz1, axis=0, keepdims=True)

        self.vW2 = momentum * self.vW2 - lr * dW2
        self.vb2 = momentum * self.vb2 - lr * db2
        self.vW1 = momentum * self.vW1 - lr * dW1
        self.vb1 = momentum * self.vb1 - lr * db1

        self.W2 = self.W2 + self.vW2
        self.b2 = self.b2 + self.vb2
        self.W1 = self.W1 + self.vW1
        self.b1 = self.b1 + self.vb1

    def predict(self, X: np.ndarray) -> np.ndarray:
        return (self.forward(X).reshape(-1) >= 0.5).astype(np.int64)

    def get_state(self) -> dict:
        return {
            "W1": self.W1.copy(),
            "b1": self.b1.copy(),
            "W2": self.W2.copy(),
            "b2": self.b2.copy(),
            "vW1": self.vW1.copy(),
            "vb1": self.vb1.copy(),
            "vW2": self.vW2.copy(),
            "vb2": self.vb2.copy(),
        }

    def set_state(self, state: dict) -> None:
        self.W1 = np.array(state["W1"], copy=True)
        self.b1 = np.array(state["b1"], copy=True)
        self.W2 = np.array(state["W2"], copy=True)
        self.b2 = np.array(state["b2"], copy=True)
        self.vW1 = np.array(state["vW1"], copy=True)
        self.vb1 = np.array(state["vb1"], copy=True)
        self.vW2 = np.array(state["vW2"], copy=True)
        self.vb2 = np.array(state["vb2"], copy=True)
