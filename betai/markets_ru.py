"""
Словарь переводов кодов API-Football → человекочитаемые названия на русском.
"""

from __future__ import annotations

# базовые рынки --------------------------------------------------------

MATCH_WINNER = {
    "Home": "Хозяев",
    "Draw": "Ничья",
    "Away": "Гости",
}

OVER_UNDER_PICK = {
    "Over": "Больше",
    "Under": "Меньше",
}

# динамически формируемые названия ------------------------------------

def ru_total(line: float, side: str) -> str:
    return f"Тотал {OVER_UNDER_PICK[side]} {line:.1f}"

def ru_ah(line: float, side: str) -> str:
    sign = "−" if side == "Home" else "+"
    team = "хозяев" if side == "Home" else "гостей"
    return f"Фора ({sign}{abs(line):.1f}) {team}"