"""Small real image trainer (PyTorch) used by TrainGuard MCP tools."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Subset, random_split
from torchvision import datasets, transforms

from trainguard.state import DATA_DIR

DEVICE = torch.device("cpu")


class TinyCNN(nn.Module):
    """Small CNN that adapts to channels, size and class count."""

    def __init__(self, in_channels: int = 1, num_classes: int = 10, image_size: int = 28) -> None:
        super().__init__()
        self.in_channels = in_channels
        self.num_classes = num_classes
        self.image_size = image_size
        spatial = max(1, image_size // 4)
        self.net = nn.Sequential(
            nn.Conv2d(in_channels, 8, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Conv2d(8, 16, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2),
            nn.Flatten(),
            nn.Linear(16 * spatial * spatial, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


def seed_everything(seed: int) -> None:
    torch.manual_seed(seed)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_model(
    lr: float,
    in_channels: int = 1,
    num_classes: int = 10,
    image_size: int = 28,
) -> tuple[TinyCNN, torch.optim.SGD, nn.CrossEntropyLoss]:
    model = TinyCNN(
        in_channels=in_channels,
        num_classes=num_classes,
        image_size=image_size,
    ).to(DEVICE)
    optimizer = torch.optim.SGD(model.parameters(), lr=lr, momentum=0.9)
    return model, optimizer, nn.CrossEntropyLoss()


def _as_rgb(img: Any) -> Any:
    return img.convert("RGB")


def _transform_for(spec: dict[str, Any]) -> transforms.Compose:
    size = int(spec["image_size"])
    if int(spec["in_channels"]) == 1:
        return transforms.Compose(
            [
                transforms.Grayscale(num_output_channels=1),
                transforms.Resize((size, size)),
                transforms.ToTensor(),
            ]
        )
    return transforms.Compose(
        [
            transforms.Lambda(_as_rgb),
            transforms.Resize((size, size)),
            transforms.ToTensor(),
        ]
    )


def _subset(dataset: Any, size: int, seed: int) -> Any:
    if size <= 0 or size >= len(dataset):
        return dataset
    generator = torch.Generator().manual_seed(seed)
    idx = torch.randperm(len(dataset), generator=generator)[:size]
    return Subset(dataset, idx.tolist())


def _torchvision_pair(spec: dict[str, Any], transform: Any) -> tuple[Any, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    name = spec["id"]
    if name == "mnist":
        train_full = datasets.MNIST(str(DATA_DIR), train=True, download=True, transform=transform)
        val_full = datasets.MNIST(str(DATA_DIR), train=False, download=True, transform=transform)
    elif name == "fashion_mnist":
        train_full = datasets.FashionMNIST(str(DATA_DIR), train=True, download=True, transform=transform)
        val_full = datasets.FashionMNIST(str(DATA_DIR), train=False, download=True, transform=transform)
    elif name == "cifar10":
        train_full = datasets.CIFAR10(str(DATA_DIR), train=True, download=True, transform=transform)
        val_full = datasets.CIFAR10(str(DATA_DIR), train=False, download=True, transform=transform)
    else:
        raise ValueError(f"Unsupported torchvision dataset: {name}")
    return train_full, val_full


def _imagefolder_pair(spec: dict[str, Any], transform: Any, seed: int) -> tuple[Any, Any]:
    root = Path(spec["path"])
    train_dir = root / "train"
    val_dir = root / "val" if (root / "val").is_dir() else root / "test"
    if train_dir.is_dir() and val_dir.is_dir():
        train_full = datasets.ImageFolder(str(train_dir), transform=transform)
        val_full = datasets.ImageFolder(str(val_dir), transform=transform)
        return train_full, val_full
    if train_dir.is_dir():
        full = datasets.ImageFolder(str(train_dir), transform=transform)
    else:
        full = datasets.ImageFolder(str(root), transform=transform)
    val_len = max(1, int(len(full) * 0.2))
    train_len = max(1, len(full) - val_len)
    if train_len + val_len != len(full):
        train_len = len(full) - val_len
    return random_split(
        full,
        [train_len, val_len],
        generator=torch.Generator().manual_seed(seed),
    )


def build_loaders(
    spec: dict[str, Any],
    train_size: int,
    val_size: int,
    batch_size: int,
    seed: int,
) -> tuple[DataLoader, DataLoader, dict[str, Any]]:
    transform = _transform_for(spec)
    if spec.get("kind") == "imagefolder":
        train_full, val_full = _imagefolder_pair(spec, transform, seed)
        num_classes = len(getattr(train_full, "classes", None) or getattr(train_full.dataset, "classes", []))
        if not num_classes:
            num_classes = int(spec.get("num_classes") or 2)
    else:
        train_full, val_full = _torchvision_pair(spec, transform)
        num_classes = int(spec.get("num_classes") or 10)

    train_ds = _subset(train_full, train_size, seed)
    val_ds = _subset(val_full, val_size, seed + 1)
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=0)
    meta = {
        **spec,
        "num_classes": num_classes,
        "train_len": len(train_ds),
        "val_len": len(val_ds),
    }
    return train_loader, val_loader, meta


def weights_finite(model: nn.Module) -> bool:
    return all(torch.isfinite(param).all().item() for param in model.parameters())


def set_optimizer_lr(optimizer: torch.optim.Optimizer, lr: float) -> None:
    for group in optimizer.param_groups:
        group["lr"] = lr


def save_checkpoint(
    path: Path,
    model: nn.Module,
    optimizer: torch.optim.Optimizer,
    meta: dict[str, Any],
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_state_dict": model.state_dict(),
        "optimizer_state_dict": optimizer.state_dict(),
        **meta,
    }
    torch.save(payload, path)
    info = {
        "name": path.name,
        "path": str(path),
        "epoch": meta.get("epoch"),
        "loss": meta.get("val_loss"),
        "accuracy": meta.get("val_acc"),
        "lr": meta.get("lr"),
        "healthy": bool(meta.get("healthy", True)),
        "is_best": bool(meta.get("is_best", False)),
        "sha256": sha256_file(path),
    }
    return info


def load_checkpoint(
    path: Path,
    model: nn.Module,
    optimizer: torch.optim.Optimizer | None = None,
) -> dict[str, Any]:
    blob = torch.load(path, map_location=DEVICE, weights_only=False)
    model.load_state_dict(blob["model_state_dict"])
    if optimizer is not None and "optimizer_state_dict" in blob:
        optimizer.load_state_dict(blob["optimizer_state_dict"])
    return blob


def _metric_from_totals(
    total_loss: float, correct: int, count: int, saw_nan: bool
) -> dict[str, Any]:
    if saw_nan or count == 0 or not math.isfinite(total_loss):
        return {
            "loss": None,
            "loss_raw": "NaN",
            "accuracy": 0.0,
            "healthy": False,
        }
    avg = total_loss / count
    return {
        "loss": round(avg, 5),
        "loss_raw": round(avg, 5),
        "accuracy": round(correct / count, 5),
        "healthy": True,
    }


def train_one_epoch(
    model: nn.Module,
    loader: DataLoader,
    optimizer: torch.optim.Optimizer,
    criterion: nn.Module,
    fault: str | None,
) -> dict[str, Any]:
    model.train()
    total_loss = 0.0
    correct = 0
    count = 0
    saw_nan = False

    for inputs, targets in loader:
        inputs = inputs.to(DEVICE)
        targets = targets.to(DEVICE)

        if fault == "stall":
            n_classes = int(getattr(model, "num_classes", 10))
            noise = torch.randint(0, n_classes, targets.shape, device=DEVICE)
            mask = torch.rand(len(targets), device=DEVICE) < 0.9
            targets = torch.where(mask, noise, targets)

        optimizer.zero_grad(set_to_none=True)
        logits = model(inputs)
        if not torch.isfinite(logits).all():
            saw_nan = True
            break

        loss = criterion(logits, targets)
        if fault == "nan_loss":
            loss = loss * float("nan")

        if not torch.isfinite(loss):
            saw_nan = True
            if fault == "nan_loss":
                with torch.no_grad():
                    for param in model.parameters():
                        param.mul_(float("nan"))
                        break
            break

        loss.backward()
        optimizer.step()
        if not weights_finite(model):
            saw_nan = True
            break

        total_loss += float(loss.item()) * len(targets)
        correct += int((logits.argmax(1) == targets).sum().item())
        count += len(targets)

    metric = _metric_from_totals(total_loss, correct, count, saw_nan)
    metric["split"] = "train"
    return metric


@torch.no_grad()
def evaluate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
) -> dict[str, Any]:
    model.eval()
    total_loss = 0.0
    correct = 0
    count = 0
    saw_nan = not weights_finite(model)

    if not saw_nan:
        for inputs, targets in loader:
            inputs = inputs.to(DEVICE)
            targets = targets.to(DEVICE)
            logits = model(inputs)
            if not torch.isfinite(logits).all():
                saw_nan = True
                break
            loss = criterion(logits, targets)
            if not torch.isfinite(loss):
                saw_nan = True
                break
            total_loss += float(loss.item()) * len(targets)
            correct += int((logits.argmax(1) == targets).sum().item())
            count += len(targets)

    metric = _metric_from_totals(total_loss, correct, count, saw_nan)
    metric["split"] = "val"
    return metric
