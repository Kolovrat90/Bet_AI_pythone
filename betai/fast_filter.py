"""Implementation of FAST filter (v4.1) for basic 1x2 lines."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict


@dataclass
class FastParams:
    k_min: float = 1.27
    k_max: float = 12.0
    p_min: float = 0.025
    p_max: float = 0.85
    EV_min: float = 0.05
    v_max: float = 0.15
    bk_min: int = 3


@dataclass
class Selection:
    side: str
    k_offer: float
    p_est: float


def market_margin(k_values: List[float]) -> float:
    return sum(1 / k for k in k_values) - 1


def fast_filter_1x2(
    k_home: float,
    k_draw: float,
    k_away: float,
    p_est: Dict[str, float],
    bk_cnt: int,
    params: FastParams | None = None,
) -> List[Selection]:
    """Return selections that pass FAST filter for 1x2 market."""
    if params is None:
        params = FastParams()

    margin = market_margin([k_home, k_draw, k_away])
    if margin > params.v_max or bk_cnt < params.bk_min:
        return []

    res: List[Selection] = []
    for side, k in (("Home", k_home), ("Draw", k_draw), ("Away", k_away)):
        pm = 1.0 / k
        if k < params.k_min or k > params.k_max:
            continue
        if pm < params.p_min or pm > params.p_max:
            continue
        p = p_est.get(side, 0.0)
        EV = p * k - 1
        if EV < params.EV_min:
            continue
        res.append(Selection(side=side, k_offer=k, p_est=p))
    return res
