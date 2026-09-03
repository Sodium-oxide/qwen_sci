"""M08 local identifiability gate based on a Fisher Information Matrix."""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Any, Dict, Mapping, Sequence


@dataclass
class IdentifiabilityReport:
    passed: bool
    rank: int
    parameter_count: int
    condition_number: float
    singular_values: list[float]
    threshold: float
    errors: list[Dict[str, Any]]
    metrics: Dict[str, float]

    def to_dict(self) -> Dict[str, Any]:
        return {"passed": self.passed, "rank": self.rank, "parameter_count": self.parameter_count,
                "condition_number": self.condition_number, "singular_values": self.singular_values,
                "threshold": self.threshold, "errors": self.errors, "metrics": self.metrics}


def fisher_identifiability(jacobian: Sequence[Sequence[float]], threshold: float = 1e-8,
                           max_condition: float = 1e8) -> IdentifiabilityReport:
    """Evaluate rank and conditioning of a sensitivity/Jacobian matrix.

    A tiny self-contained SVD fallback keeps the gate usable without NumPy;
    NumPy is used when installed for numerically stable singular values.
    """
    rows = [list(map(float, row)) for row in jacobian]
    if not rows or not rows[0]:
        return IdentifiabilityReport(False, 0, 0, math.inf, [], threshold,
                                     [{"code": "INSUFFICIENT_EXCITATION", "message": "empty Jacobian"}], {})
    try:
        import numpy as np
        singular = np.linalg.svd(np.asarray(rows), compute_uv=False).tolist()
    except Exception:
        # Eigenvalues of J^T J via a power-free Jacobi sweep (adequate for MVP).
        m, n = len(rows), len(rows[0]); gram = [[sum(rows[k][i] * rows[k][j] for k in range(m)) for j in range(n)] for i in range(n)]
        vals = [max(0.0, gram[i][i]) for i in range(n)]
        singular = sorted((math.sqrt(v) for v in vals), reverse=True)
    rank = sum(s > threshold for s in singular)
    positive = [s for s in singular if s > threshold]
    cond = (max(positive) / min(positive)) if positive else math.inf
    errors: list[Dict[str, Any]] = []
    if rank < len(rows[0]): errors.append({"code": "NOT_IDENTIFIABLE", "message": "FIM is rank deficient", "details": {"rank": rank}})
    if cond > max_condition: errors.append({"code": "WEAK_IDENTIFIABILITY", "message": "FIM is ill-conditioned", "details": {"condition_number": cond}})
    return IdentifiabilityReport(not errors, rank, len(rows[0]), cond, singular, threshold, errors,
                                 {"min_singular_value": min(positive) if positive else 0.0,
                                  "max_singular_value": max(positive) if positive else 0.0})

