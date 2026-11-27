"""Dominant foreground colours of a product photo (numpy k-means, deterministic)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

K = 3
WORK_SIDE = 128


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    c = np.asarray(c, dtype=float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def photo_colours(path: Path, k: int = K) -> list[dict]:
    """Up to ``k`` dominant foreground colours, biggest first: ``{"hex": "#rrggbb", "linear": [r, g, b]}``.
    Near-white pixels (all channels over 235) and a near-uniform border colour count as background."""
    try:
        img = Image.open(path)
        img.draft("RGB", (WORK_SIDE * 2, WORK_SIDE * 2))
        img = img.convert("RGB")
        img.thumbnail((WORK_SIDE, WORK_SIDE), Image.BILINEAR)
    except Exception:  # noqa: BLE001 - colour facts are advisory only
        return []
    px = np.asarray(img, dtype=float)
    h, w, _ = px.shape
    border = np.concatenate([px[0], px[-1], px[:, 0], px[:, -1]])
    background = (px > 235).all(axis=2)
    if border.std(axis=0).max() < 12:
        background |= np.abs(px - np.median(border, axis=0)).max(axis=2) < 20
    flat = px.reshape(-1, 3)
    fg = flat[~background.reshape(-1)]
    if len(fg) == 0:
        fg = flat[~(flat > 235).all(axis=1)]
    if len(fg) == 0:
        return []
    k = min(k, len(np.unique(fg, axis=0)))
    order = np.argsort((fg * np.array([0.2126, 0.7152, 0.0722])).sum(axis=1), kind="stable")
    centres = fg[order[[int((2 * i + 1) * len(fg) / (2 * k)) for i in range(k)]]]
    for _ in range(12):
        labels = np.argmin(((fg[:, None, :] - centres[None]) ** 2).sum(axis=2), axis=1)
        for j in range(k):
            if (labels == j).any():
                centres[j] = fg[labels == j].mean(axis=0)
    labels = np.argmin(((fg[:, None, :] - centres[None]) ** 2).sum(axis=2), axis=1)
    sizes = np.bincount(labels, minlength=k)
    out = []
    for j in np.argsort(-sizes, kind="stable"):
        if sizes[j] == 0:
            continue
        rgb = np.clip(np.rint(centres[j]), 0, 255).astype(int)
        lin = srgb_to_linear(rgb / 255.0)
        out.append({"hex": "#%02x%02x%02x" % tuple(rgb), "linear": [round(float(x), 3) for x in lin]})
    return out
