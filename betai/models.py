"""
Формулы Edge, Kelly, масштаб '5% × N', лимиты ≤10% / матч≤30%,
а также Fast-Screen: quick_prob, value_approx, калибровка и shrinkage.
"""

from __future__ import annotations
from typing import List
import math

from pydantic import BaseModel, Field

# Параметры банк-менеджмента
EDGE_MIN = 0.05
BANK_PORTFOLIO = 0.05      # 5 % на портфель

# Настройки shrinkage (взвешивание модели и рынка)
SHRINKAGE_ALPHA = 0.7  # вес модели
SHRINKAGE_BETA = 0.3   # вес рынка


class Outcome(BaseModel):
    fixture_id: int
    date: str      # ISO 8601 MSK
    time: str      # HH:MM MSK
    league: str
    match: str
    market: str
    pick_ru: str
    line: float | None
    k_dec: float
    p_model: float
    flag_url: str = ""         # URL флага или логотипа лиги

    # расчётные поля
    edge: float = Field(0, ge=-1)
    f_raw: float = 0
    f_final: float = 0
    stake_eur: float = 0

    def compute_edge(self) -> None:
        """Стандартный расчёт edge и raw Kelly."""
        p_book = 1 / self.k_dec
        self.edge = self.p_model / p_book - 1
        if self.edge > 0:
            self.f_raw = self.edge / (self.k_dec - 1)
        else:
            self.f_raw = 0


def allocate_bank(outs: List[Outcome], bank: float) -> None:
    """Масштабируем Kelly под фикс-total-risk и лимиты, с компенсацией округлений."""
    value_outs = [o for o in outs if o.f_raw > 0]
    if not value_outs:
        return

    # Цель по риску: 5% на каждое value
    F_target = BANK_PORTFOLIO * len(value_outs)
    F_raw_sum = sum(o.f_raw for o in value_outs)
    scale = F_target / F_raw_sum if F_raw_sum else 0

    # 1) первый проход: лимит 10% на исход
    for o in value_outs:
        o.f_final = min(o.f_raw * scale, 0.10)

    # 2) второй проход: лимит 30% на весь матч
    by_fixture: dict[int, List[Outcome]] = {}
    for o in value_outs:
        by_fixture.setdefault(o.fixture_id, []).append(o)
    for fixture_outs in by_fixture.values():
        total = sum(o.f_final for o in fixture_outs)
        if total > 0.30:
            k = 0.30 / total
            for o in fixture_outs:
                o.f_final *= k

    # 3) вычисляем ставки в € с двумя знаками
    raw_stakes = [round(bank * o.f_final, 2) for o in value_outs]
    int_stakes = [int(round(s)) for s in raw_stakes]

    # 4) компенсация округления: привести сумму к желаемой
    desired_total = int(round(bank * F_target))
    diff = desired_total - sum(int_stakes)
    if diff != 0:
        # добавляем или убираем разницу у ставки с наибольшим f_final
        idx = max(range(len(value_outs)), key=lambda i: value_outs[i].f_final)
        int_stakes[idx] += diff

    # 5) сохраняем в объекты
    for o, st in zip(value_outs, int_stakes):
        o.stake_eur = st


# -----------------------------------------------------------------------------
# Fast-Screen: быстрые оценки p_est и грубый value

def quick_prob(
    elo_home: float,
    elo_away: float,
    hfa: float = 0.0,
) -> tuple[float, float, float]:
    """
    Быстрая оценка вероятностей (без Poisson):
      ΔElo = elo_home + hfa – elo_away
      p_home = 1 / (1 + 10^(–ΔElo/400))
      p_draw ≈ 0.24 · exp(–|ΔElo| / 600)
      p_away = 1 – p_home – p_draw
    Возвращает (p_home, p_draw, p_away).
    """
    d_elo = elo_home + hfa - elo_away
    p_home = 1.0 / (1.0 + 10 ** (-d_elo / 400.0))
    p_draw = 0.24 * math.exp(-abs(d_elo) / 600.0)
    p_away = max(0.0, 1.0 - p_home - p_draw)
    return p_home, p_draw, p_away


def value_approx(
    p_est: float,
    k_mean: float
) -> float:
    """
    Грубая оценка value для рынка:
      value_approx = p_est * k_mean
    """
    return p_est * k_mean


# -----------------------------------------------------------------------------
# Калибровка и Shrinkage (место для будущей доработки)

def calibrate_platt(
    logits: List[float],
    labels: List[int],
) -> tuple[float, float]:
    """
    Обучение Platt-сигмоида (заглушка).
    """
    return 1.0, 0.0


def apply_shrinkage(
    p_model: float,
    k_mean: float
) -> float:
    """
    Shrinkage: p_final = α·p_model + β·(1/k_mean)
    """
    p_market = 1.0 / k_mean if k_mean > 0 else 0.0
    return SHRINKAGE_ALPHA * p_model + SHRINKAGE_BETA * p_market
