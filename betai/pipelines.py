# betai/pipelines.py

"""
Сбор данных: fixtures → Fast-Screen → detailed_analysis → Outcome[] → allocate_bank.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any
import pytz
from tqdm import tqdm

from .api import get_fixtures, get_odds, get_predictions, get_team_form, load_elo, save_elo
from .odds_parser import parse_odds
from .pred_parser import parse_predictions
from .models import (
    Outcome,
    allocate_bank,
    quick_prob,
    value_approx,
    apply_shrinkage,
)

MSK = pytz.timezone("Europe/Moscow")

# Таблица ТОП-лиг (по рейтингу API-Football)
LEAGUE_RANKING = [
    39, 140, 135, 78, 61,
    2, 3, 848, 94, 88,
    203, 78, 253, 262, 71,
    179, 180, 3, 848, 268,
    322, 571, 129, 63,
    384, 301, 98, 81,
]


def quick_screen(
    days: int,
    top_n: int,
    completeness_thresh: float = 0.8,
    value_thresh: float = 0.95,
    p_min: float = 0.25,
    p_max: float = 0.75,
    max_events: int = 30,
    hfa: float = 60.0,
) -> List[Dict[str, Any]]:
    """
    Fast-Screen:
    1. Фильтрация лиг и дат
    2. Проверка completeness: у каждой команды ≥10 матчей, заполненность ≥ completeness_thresh
    3. Быстрый расчёт p_est по Elo и HFA
    4. Грубый value_approx = p_est * k_mean, фильтр по value_thresh и [p_min, p_max]
    5. Сортировка по убыванию value_approx, top max_events
    Возвращает список словарей с нужными полями для detailed_analysis.
    """
    today_utc = datetime.now(timezone.utc).date()
    candidates: List[Dict[str, Any]] = []

    allowed_leagues = set(LEAGUE_RANKING[:top_n])
    cutoff = datetime.now(timezone.utc) + timedelta(minutes=5)

    for d in range(days):
        day = today_utc + timedelta(days=d)
        fixtures = get_fixtures(day).get("response", [])

        for f in fixtures:
            lid = f["league"]["id"]
            if lid not in allowed_leagues:
                continue

            ts = datetime.fromtimestamp(f["fixture"]["timestamp"], tz=timezone.utc)
            if ts <= cutoff:
                continue

            home = f["teams"]["home"]["id"]
            away = f["teams"]["away"]["id"]

            # Проверяем completeness данных по командам
            home_form = get_team_form(home, last_n=10)
            away_form = get_team_form(away, last_n=10)
            if len(home_form) < 10 or len(away_form) < 10:
                continue
            # TODO: проверка фактического заполнения полей ≥ completeness_thresh

            # Загружаем/вычисляем Elo на текущую дату
            date_str = day.isoformat()
            eh = load_elo(home, date_str) or 1500.0
            ea = load_elo(away, date_str) or 1500.0

            # Быстрый p_est
            p_h, p_d, p_a = quick_prob(eh, ea, hfa)

            # Сбор средней линии 1X2
            odds = get_odds(f["fixture"]["id"]).get("response", [])
            # возьмём только рынок Match Winner, первую книгу
            bk = odds[0]["bookmakers"][0]["bets"] if odds and odds[0]["bookmakers"] else []
            k_list = []
            for bet in bk:
                if bet["name"] == "Match Winner":
                    k_list = [float(v["odd"]) for v in bet["values"]]
                    break
            if len(k_list) < 2:
                continue
            k_mean = sum(k_list[:2]) / 2  # Home vs Away

            # Грубый value для Home и Away (игнорируем ничью)
            for side, p_est in (("Home", p_h), ("Away", p_a)):
                val = value_approx(p_est, k_mean)
                if val >= value_thresh and p_min <= p_est <= p_max:
                    candidates.append({
                        **f,
                        "side": side,
                        "p_est": p_est,
                        "k_mean": k_mean,
                        "value_approx": val,
                    })

    # Сортируем и берём топ
    candidates.sort(key=lambda x: x["value_approx"], reverse=True)
    return candidates[:max_events]


def detailed_analysis(
    candidates: List[Dict[str, Any]],
    edge_min: float,
) -> List[Outcome]:
    """
    Для каждого кандидата:
    1. Парсим полные odds и predictions
    2. Получаем точный p_model, применяем shrinkage
    3. Создаём Outcome, считаем edge
    4. Фильтруем по edge_min
    """
    outcomes: List[Outcome] = []

    for c in tqdm(candidates, desc="detailed analysis", leave=False):
        fid = c["fixture"]["id"]
        dt_utc = datetime.fromtimestamp(c["fixture"]["timestamp"], tz=timezone.utc)
        dt_msk = dt_utc.astimezone(MSK)

        odds_json = get_odds(fid)
        preds_json = get_predictions(fid)
        preds = parse_predictions(preds_json)

        for o in parse_odds(odds_json):
            # точный p_model: разделяем 1X2 от других рынков
            if o["market"] == "1X2":
                # просто берём preds["1X2"][side]
                pm = preds.get("1X2", {}).get(o["side"])
            elif o["market"] in ("Total", "AH"):
                # для тоталов и азиатских фор: preds["Total" or "AH"][line][side]
                pm = preds.get(o["market"], {}) \
                           .get(o["line"], {}) \
                           .get(o["side"])
            else:
                # на всякий случай: тот же подход
                pm = preds.get(o["market"], {}) \
                           .get(o["line"], {}) \
                           .get(o["side"])

            if pm is None:
                continue

            # применяем shrinkage
            p_final = apply_shrinkage(pm, c["k_mean"])

            out = Outcome(
                fixture_id=fid,
                date=dt_msk.strftime("%Y-%m-%d"),
                time=dt_msk.strftime("%H:%M"),
                league=c["league"]["name"],
                match=f'{c["teams"]["home"]["name"]} – {c["teams"]["away"]["name"]}',
                market=o["market"],
                pick_ru=o["pick_ru"],
                line=o["line"],
                k_dec=o["k_dec"],
                p_model=p_final,
                flag_url=c["league"].get("flag") or c["league"].get("logo", ""),
            )
            out.compute_edge()
            if out.edge >= edge_min:
                outcomes.append(out)

    return outcomes


def scan_days(days: int, edge_min: float, top_n: int) -> List[Outcome]:
    """
    Объединяем fast-screen и detailed-analysis:
      1) quick_screen → кандидаты
      2) detailed_analysis → точные Outcome
    """
    cand = quick_screen(days, top_n)
    detailed = detailed_analysis(cand, edge_min)
    return detailed


def full_pipeline(
    days: int,
    edge_min: float,
    bank: float,
    top_n: int,
) -> List[Outcome]:
    """
    Полный конвейер: scan_days → allocate_bank → сортировка финальных ставок.
    """
    outs = scan_days(days, edge_min, top_n)
    allocate_bank(outs, bank)
    # только положительные ставки
    outs = [o for o in outs if o.stake_eur > 0]
    # сортировка: по убыванию edge, затем по дате/времени
    outs.sort(key=lambda x: (-x.edge, x.date, x.time))
    return outs
