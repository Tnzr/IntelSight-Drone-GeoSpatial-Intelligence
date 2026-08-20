from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np


_POPCOUNT = np.array([int(value).bit_count() for value in range(256)], dtype=np.uint8)


@dataclass(frozen=True)
class MatchConfig:
    grid_size: int = 160
    neighborhood: int = 1
    max_hamming_distance: int = 64
    min_similarity: float = 0.72
    dynamic_threshold_sigma: float = 2.0
    max_matches: int = 100
    device: str = "auto"


@dataclass(frozen=True)
class BinaryFeatureMatch:
    query_index: int
    train_index: int
    distance: int
    similarity: float


def bbox_center(box: Iterable[int]) -> tuple[float, float]:
    x1, y1, x2, y2 = box
    return (x1 + x2) / 2, (y1 + y2) / 2


def spatial_cell(box: Iterable[int], grid_size: int) -> tuple[int, int]:
    center_x, center_y = bbox_center(box)
    return int(center_x // grid_size), int(center_y // grid_size)


def build_spatial_buckets(
    gallery: dict[int, dict[str, Any]],
    grid_size: int,
) -> dict[tuple[int, int], list[int]]:
    buckets: dict[tuple[int, int], list[int]] = {}
    for identity_id, item in gallery.items():
        cell = spatial_cell(item["xyxy"], grid_size)
        buckets.setdefault(cell, []).append(identity_id)
    return buckets


def spatial_candidate_ids(
    box: Iterable[int],
    buckets: dict[tuple[int, int], list[int]],
    config: MatchConfig,
) -> set[int]:
    cell_x, cell_y = spatial_cell(box, config.grid_size)
    candidates: set[int] = set()
    for offset_y in range(-config.neighborhood, config.neighborhood + 1):
        for offset_x in range(-config.neighborhood, config.neighborhood + 1):
            candidates.update(buckets.get((cell_x + offset_x, cell_y + offset_y), ()))
    return candidates


def _validated_descriptors(descriptors: np.ndarray) -> np.ndarray:
    values = np.asarray(descriptors)
    if values.ndim != 2:
        raise ValueError(f"Expected a 2D descriptor matrix, received shape {values.shape}")
    if values.dtype != np.uint8:
        raise TypeError(f"ORB descriptors must use uint8, received {values.dtype}")
    return np.ascontiguousarray(values)


def _resolve_torch_device(device: str) -> str | None:
    if device == "cpu":
        return None
    try:
        import torch
    except ImportError:
        return None
    if device == "auto":
        return "cuda" if torch.cuda.is_available() else None
    if device.startswith("cuda") and torch.cuda.is_available():
        return device
    return None


def pairwise_hamming_distance(
    current: np.ndarray,
    previous: np.ndarray,
    device: str = "auto",
) -> np.ndarray:
    current_values = _validated_descriptors(current)
    previous_values = _validated_descriptors(previous)
    if current_values.shape[1] != previous_values.shape[1]:
        raise ValueError("Descriptor matrices must have the same width")
    if current_values.shape[0] == 0 or previous_values.shape[0] == 0:
        return np.empty((current_values.shape[0], previous_values.shape[0]), dtype=np.int16)

    torch_device = _resolve_torch_device(device)
    if torch_device is not None:
        import torch

        current_tensor = torch.as_tensor(current_values, device=torch_device)
        previous_tensor = torch.as_tensor(previous_values, device=torch_device)
        lookup = torch.as_tensor(_POPCOUNT, device=torch_device)
        xor_values = torch.bitwise_xor(current_tensor[:, None, :], previous_tensor[None, :, :])
        distances = lookup[xor_values.long()].sum(dim=2)
        return distances.to(device="cpu", dtype=torch.int16).numpy()

    xor_values = np.bitwise_xor(current_values[:, None, :], previous_values[None, :, :])
    return _POPCOUNT[xor_values].sum(axis=2, dtype=np.int16)


def binary_similarity_matrix(
    current: np.ndarray,
    previous: np.ndarray,
    device: str = "auto",
) -> np.ndarray:
    distances = pairwise_hamming_distance(current, previous, device=device)
    descriptor_bits = max(1, _validated_descriptors(current).shape[1] * 8)
    return 1.0 - distances.astype(np.float32) / descriptor_bits


def mutual_nearest_matches(
    current: np.ndarray | None,
    previous: np.ndarray | None,
    config: MatchConfig | None = None,
) -> list[BinaryFeatureMatch]:
    if current is None or previous is None:
        return []
    settings = config or MatchConfig()
    current_values = _validated_descriptors(current)
    previous_values = _validated_descriptors(previous)
    if current_values.shape[0] == 0 or previous_values.shape[0] == 0:
        return []

    distances = pairwise_hamming_distance(current_values, previous_values, settings.device)
    descriptor_bits = current_values.shape[1] * 8
    similarities = 1.0 - distances.astype(np.float32) / descriptor_bits
    row_best = similarities.argmax(axis=1)
    column_best = similarities.argmax(axis=0)
    row_scores = similarities[np.arange(similarities.shape[0]), row_best]
    adaptive_threshold = float(similarities.mean() + settings.dynamic_threshold_sigma * similarities.std())
    threshold = max(settings.min_similarity, min(0.98, adaptive_threshold))

    matches = []
    for query_index, train_index in enumerate(row_best.tolist()):
        distance = int(distances[query_index, train_index])
        similarity = float(row_scores[query_index])
        if column_best[train_index] != query_index:
            continue
        if distance > settings.max_hamming_distance or similarity < threshold:
            continue
        matches.append(BinaryFeatureMatch(query_index, train_index, distance, similarity))
    matches.sort(key=lambda match: (match.distance, -match.similarity, match.query_index, match.train_index))
    return matches[:settings.max_matches]
