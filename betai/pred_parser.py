# betai/pred_parser.py

"""
Парсинг /predictions – достаём вероятности модели для 1X2,
основанные на поле predictions.percent из API-Football.
"""

from __future__ import annotations
from typing import Dict

def parse_predictions(data: Dict) -> Dict:
    """
    Возвращает словарь вида:
    {
      '1X2': {'Home': 0.50, 'Draw': 0.50, 'Away': 0.00},
      'Total': {},  # нет прогнозов в этом эндпоинте
      'AH': {},     # нет прогнозов в этом эндпоинте
    }
    """
    resp = data.get("response")
    if not resp:
        return {"1X2": {}, "Total": {}, "AH": {}}

    pr = resp[0].get("predictions", {})
    pct = pr.get("percent", {})

    # percent хранит строки вроде "50%", "0%", "25%"
    try:
        home = float(pct.get("home", "0%").strip("%")) / 100
        draw = float(pct.get("draw", "0%").strip("%")) / 100
        away = float(pct.get("away", "0%").strip("%")) / 100
    except Exception:
        home = draw = away = 0.0

    return {
        "1X2": {"Home": home, "Draw": draw, "Away": away},
        "Total": {},  # пока нет прогноза
        "AH": {},     # пока нет прогноза
    }
