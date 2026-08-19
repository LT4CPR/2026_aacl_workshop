from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment


@dataclass
class AlignmentResult:
    aligned_pairs: list[dict[str, Any]]
    unmatched_gold: list[int]
    unmatched_system: list[int]
    total_weight: float


def align_weight_matrix_bipartite(
    weight_matrix: np.ndarray,
    threshold: float = 0.0,
) -> AlignmentResult:
    """Solve maximum-weight one-to-one matching."""

    if weight_matrix.ndim != 2:
        raise ValueError("weight_matrix must be a 2D matrix")

    num_gold, num_system = weight_matrix.shape

    if num_gold == 0 and num_system == 0:
        return AlignmentResult([], [], [], 0.0)

    if num_gold == 0:
        return AlignmentResult([], [], list(range(num_system)), 0.0)

    if num_system == 0:
        return AlignmentResult([], list(range(num_gold)), [], 0.0)

    if not np.isfinite(weight_matrix).all():
        raise ValueError("weight_matrix must contain only finite values")
    if not np.isfinite(threshold):
        raise ValueError("threshold must be finite")
    if threshold < 0.0:
        raise ValueError("threshold must be non-negative")

    eligible_weights = np.where(weight_matrix > threshold, weight_matrix, 0.0)
    row_ind, col_ind = linear_sum_assignment(eligible_weights, maximize=True)

    aligned_pairs = []
    matched_gold = set()
    matched_system = set()
    total_weight = 0.0

    for i, j in zip(row_ind, col_ind):
        weight = float(weight_matrix[i, j])
        if weight <= threshold:
            continue
        aligned_pairs.append({
            "gold_index": int(i),
            "system_index": int(j),
            "weight": weight,
        })
        matched_gold.add(int(i))
        matched_system.add(int(j))
        total_weight += weight

    unmatched_gold = [
        i for i in range(num_gold)
        if i not in matched_gold
    ]

    unmatched_system = [
        j for j in range(num_system)
        if j not in matched_system
    ]

    return AlignmentResult(
        aligned_pairs=aligned_pairs,
        unmatched_gold=unmatched_gold,
        unmatched_system=unmatched_system,
        total_weight=total_weight,
    )
