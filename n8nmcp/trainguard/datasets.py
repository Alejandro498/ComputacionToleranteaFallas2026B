"""Dataset catalog: torchvision, local ImageFolder, or a ZIP URL."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

from trainguard.state import DATA_DIR

CUSTOM_DIR = DATA_DIR / "custom"
UPLOADS_DIR = DATA_DIR / "uploads"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}

BUILTIN: dict[str, dict[str, Any]] = {
    "mnist": {
        "id": "mnist",
        "name": "MNIST",
        "kind": "torchvision",
        "in_channels": 1,
        "image_size": 28,
        "num_classes": 10,
        "download": True,
    },
    "fashion_mnist": {
        "id": "fashion_mnist",
        "name": "Fashion-MNIST",
        "kind": "torchvision",
        "in_channels": 1,
        "image_size": 28,
        "num_classes": 10,
        "download": True,
    },
    "cifar10": {
        "id": "cifar10",
        "name": "CIFAR-10",
        "kind": "torchvision",
        "in_channels": 3,
        "image_size": 32,
        "num_classes": 10,
        "download": True,
    },
}


def _looks_like_image_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    return any(child.suffix.lower() in IMAGE_EXTS for child in path.iterdir() if child.is_file())


def _is_class_folder_root(path: Path) -> bool:
    if not path.is_dir():
        return False
    class_dirs = [p for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")]
    return bool(class_dirs) and all(_looks_like_image_dir(p) for p in class_dirs)


def find_imagefolder_root(path: Path) -> Path:
    path = path.resolve()
    if (path / "train").is_dir() and _is_class_folder_root(path / "train"):
        return path
    if _is_class_folder_root(path):
        return path
    for child in sorted(path.rglob("*")):
        if child.is_dir() and (child / "train").is_dir() and _is_class_folder_root(child / "train"):
            return child
    for child in sorted(path.rglob("*")):
        if child.is_dir() and _is_class_folder_root(child):
            return child
    raise ValueError(
        f"No ImageFolder found under {path}. "
        "Expected train/<class>/*.png or <class>/*.png"
    )


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    dest = dest.resolve()
    dest.mkdir(parents=True, exist_ok=True)
    for info in zf.infolist():
        target = (dest / info.filename).resolve()
        if dest not in target.parents and target != dest:
            raise ValueError(f"Unsafe zip path: {info.filename}")
    zf.extractall(dest)


def fetch_dataset_url(url: str, dest: Path) -> Path:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("dataset_url must be http(s)")
    dest.mkdir(parents=True, exist_ok=True)
    with urlopen(url, timeout=60) as response:  # noqa: S310 — user-supplied demo URL
        payload = response.read()
    zip_path = dest / "dataset.zip"
    zip_path.write_bytes(payload)
    extract_dir = dest / "extracted"
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        _safe_extract(zf, extract_dir)
    return find_imagefolder_root(extract_dir)


def scan_custom_datasets() -> list[dict[str, Any]]:
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    found: list[dict[str, Any]] = []
    for child in sorted(CUSTOM_DIR.iterdir()):
        if not child.is_dir() or child.name.startswith("_") or child.name.startswith("."):
            continue
        try:
            root = find_imagefolder_root(child)
        except ValueError:
            continue
        found.append(
            {
                "id": f"custom:{child.name}",
                "name": child.name,
                "kind": "imagefolder",
                "path": str(root),
                "in_channels": 3,
                "image_size": 32,
            }
        )
    return found


def list_datasets() -> dict[str, Any]:
    custom = scan_custom_datasets()
    builtin = [
        {k: v for k, v in spec.items() if k != "download"} | {"available": True}
        for spec in BUILTIN.values()
    ]
    return {
        "default": "auto",
        "builtin": builtin,
        "custom": custom,
        "datasets": [
            {
                "id": "auto",
                "name": "Auto (carpeta custom o MNIST)",
                "kind": "resolver",
            },
            *builtin,
            *custom,
        ],
        "hint": (
            "Pon imágenes en data/custom/<nombre>/train/<clase>/ "
            "o manda dataset=fashion_mnist | cifar10 | custom + dataset_url"
        ),
    }


def resolve_dataset(
    dataset: str = "auto",
    dataset_path: str = "",
    dataset_url: str = "",
    image_size: int = 0,
    run_id: str = "",
) -> dict[str, Any]:
    """Turn n8n/MCP args into a concrete loader spec."""
    name = (dataset or "auto").strip().lower()
    path = (dataset_path or "").strip()
    url = (dataset_url or "").strip()

    if name.startswith("custom:"):
        folder = name.split(":", 1)[1]
        path = path or str(CUSTOM_DIR / folder)
        name = "custom"

    if name == "auto":
        if url:
            name = "custom"
        elif path:
            name = "custom"
        else:
            custom = scan_custom_datasets()
            if custom:
                name = "custom"
                path = custom[0]["path"]
            else:
                name = "mnist"

    if name in BUILTIN:
        spec = dict(BUILTIN[name])
        if image_size > 0:
            spec["image_size"] = image_size
        spec["path"] = None
        spec["url"] = None
        spec["resolved"] = spec["id"]
        return spec

    if name != "custom":
        raise ValueError(
            f"Unknown dataset '{dataset}'. Use mnist | fashion_mnist | cifar10 | custom | auto"
        )

    if url:
        dest = UPLOADS_DIR / (run_id or "latest")
        root = fetch_dataset_url(url, dest)
    elif path:
        root = find_imagefolder_root(Path(path))
    else:
        custom = scan_custom_datasets()
        if not custom:
            raise ValueError(
                "dataset=custom but no dataset_path/dataset_url and data/custom is empty"
            )
        root = Path(custom[0]["path"])

    spec = {
        "id": "custom",
        "name": root.name,
        "kind": "imagefolder",
        "in_channels": 3,
        "image_size": image_size or 32,
        "num_classes": None,
        "path": str(root),
        "url": url or None,
        "resolved": "custom",
    }
    return spec
