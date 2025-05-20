# betai/pipelines.py
"""
Сбор данных: fixtures → quick_screen → detailed_analysis → Outcome[].
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, date
from typing import List, Dict, Any

import pytz
from tqdm import tqdm

from .api import (
    get_fixtures,
    get_odds,
    get_predictions,
    get_team_form,
    load_elo,
    save_elo,
)
from .odds_parser import parse_odds
from .pred_parser import parse_predictions
from .models import (
    Outcome,
    quick_prob,
    value_approx,
    apply_shrinkage,
)

MSK = pytz.timezone("Europe/Moscow")

# --------------------------------------------------------------------------------------
# 1. Первичный скрининг («быстрый экран»)
# --------------------------------------------------------------------------------------

#: топ-лиги по «рэнкингу» API-Football (менее качественные лиги – ниже в списке)
LEAGUE_RANKING: list[int] = [
    39, 140, 135, 78, 61, 2, 3, 848, 94, 88,
    203, 253, 262, 71, 179, 180, 268, 322, 571,
    129, 63, 384, 301, 98, 81,
]


def _best_flag(lg: Dict[str, Any]) -> str:
    """
    Для национальных чемпионатов в API приходит поле `flag`,
    для международных – часто только `logo`. Берём, что есть.
    """
    return lg.get("flag") or lg.get("logo", "")


def quick_screen(
    days: int,
    top_n: int,
    *,
    completeness: float = 0.80,
    value_thr: float = 0.95,
    p_low: float = 0.25,
    p_high: float = 0.75,
    max_events: int = 30,
    hfa: float = 60.0,
) -> List[Dict[str, Any]]:
    """
    Быстрый первичный скрин:

    1. Загружаем *fixtures* на N дней вперёд и отбрасываем всё, что не из ТОП-top_n лиг.
    2. Проверяем, что по обеим командам есть ≥10 последних матчей с заполненностью
       не ниже *completeness* (сейчас только кол-во матчей; детализация – TODO).
    3. Через Elo + HFA оцениваем вероятности p_est (Home/Draw/Away).
    4. Собираем усреднённую линию 1×2 (Match Winner) → k_mean.
    5. Считаем value≈ = p_est × k_mean.
       Берём только исходы, где value≈ ≥ *value_thr* и p_est∈[p_low; p_high].
    6. У каждого матча оставляем **один** исход с максимальным value≈,
       чтобы в «глубокий анализ» не передавать дубликаты (Home и Away).
    7. Сортируем по value≈ ↓ и обрезаем до *max_events*.
    """
    today_utc: date = datetime.now(timezone.utc).date()
    allowed_leagues = set(LEAGUE_RANKING[: top_n])
    not_started_cutoff = datetime.now(timezone.utc) + timedelta(minutes=5)

    cand: list[dict[str, Any]] = []

    for d in range(days):
        day = today_utc + timedelta(days=d)
        fixtures = get_fixtures(day).get("response", [])

        for f in fixtures:
            lg = f["league"]
            lid = lg["id"]
            if lid not in allowed_leagues:
                continue

            ts = datetime.fromtimestamp(
                f["fixture"]["timestamp"], tz=timezone.utc
            )
            if ts <= not_started_cutoff:  # матч почти начался
                continue

            home_id = f["teams"]["home"]["id"]
            away_id = f["teams"]["away"]["id"]

            home_form = get_team_form(home_id, last_n=10)
            away_form = get_team_form(away_id, last_n=10)
            if len(home_form) < 10 or len(away_form) < 10:
                continue  # неполные данные

            # --- Elo на текущий день ---
            date_key = day.isoformat()
            elo_h = load_elo(home_id, date_key) or 1500.0
            elo_a = load_elo(away_id, date_key) or 1500.0

            p_h, p_d, p_a = quick_prob(elo_h, elo_a, hfa)

            odds_json = get_odds(f["fixture"]["id"]).get("response", [])
            if not odds_json or not odds_json[0]["bookmakers"]:
                continue
            bet_mw = odds_json[0]["bookmakers"][0]["bets"]
            k_vals = next(
                (
                    [float(v["odd"]) for v in bet["values"]]
                    for bet in bet_mw
                    if bet["name"] == "Match Winner"
                ),
                [],
            )
            if len(k_vals) != 3:
                continue

            home_k, draw_k, away_k = k_vals
            sides = [
                ("Home", p_h, home_k),
                ("Draw", p_d, draw_k),
                ("Away", p_a, away_k),
            ]

            # ищем лучший value≈ для матча
            best_val = 0.0
            best_side: dict[str, Any] | None = None
            for side, p_est, k in sides:
                val = value_approx(p_est, k)
                if val >= value_thr and p_low <= p_est <= p_high and val > best_val:
                    best_val = val
                    best_side = dict(
                        side=side,
                        p_est=p_est,
                        k_mean=k,
                        value_approx=val,
                    )

            if best_side:
                cand.append(
                    {
                        "fixture": f["fixture"],
                        "league": {
                            "id": lid,
                            "name": lg["name"],
                            "flag": _best_flag(lg),
                        },
                        "teams": f["teams"],
                        **best_side,
                    }
                )

    cand.sort(key=lambda x: x["value_approx"], reverse=True)
    return cand[: max_events]


# --------------------------------------------------------------------------------------
# 2. Глубокий анализ (точные вероятности + edge)
# --------------------------------------------------------------------------------------


def detailed_analysis(candidates: List[Dict[str, Any]], edge_min: float) -> List[Outcome]:
    """
    Для каждого кандидата тянем market-odds + predictions → считаем p_model, edge,
    применяем ограничения *edge_min*. Возвращаем список Outcome.
    """
    outs: list[Outcome] = []

    for c in tqdm(candidates, desc="detailed analysis", leave=False):
        fid = c["fixture"]["id"]
        dt_utc = datetime.fromtimestamp(c["fixture"]["timestamp"], tz=timezone.utc)
        dt_msk = dt_utc.astimezone(MSK)

        odds_json = get_odds(fid)
        preds_json = get_predictions(fid)

        preds = parse_predictions(preds_json)  # {market: {line: {side: p}}}

        for o in parse_odds(odds_json):  # generator of dicts (market/side/line/k_dec/pick_ru)
            # анализируем только тот side, что прошёл скрин
            if o["side"] != c["side"]:
                continue

            # точная вероятность модели
            p_raw = (
                preds.get(o["market"], {}).get(o["line"], {}).get(o["side"])
            )
            if p_raw is None:
                continue

            p_model = apply_shrinkage(p_raw, c["k_mean"])

            out = Outcome(
                fixture_id=fid,
                date=dt_msk.strftime("%Y-%m-%d"),
                time=dt_msk.strftime("%H:%M"),
                league=c["league"]["name"],
                match=f["teams"]["home"]["name"] + " – " + f["teams"]["away"]["name"],
                market=o["market"],
                pick_ru=o["pick_ru"],
                line=o["line"],
                k_dec=o["k_dec"],
                p_model=p_model,
                flag_url=c["league"]["flag"],
            )
            out.compute_edge()
            if out.edge >= edge_min:
                outs.append(out)

    return outs


# --------------------------------------------------------------------------------------
# 3. Склейка: быстрый + глубокий
# --------------------------------------------------------------------------------------


def scan_days(days: int, edge_min: float, top_n: int) -> List[Outcome]:
    """
    Комбинирует quick_screen → detailed_analysis.
    """
    cand = quick_screen(days, top_n)
    return detailed_analysis(cand, edge_min)
