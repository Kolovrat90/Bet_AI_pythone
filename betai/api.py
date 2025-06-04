"""
Тонкая обёртка над API-Football v3 + файл-кеш SQLite.
"""

from __future__ import annotations
import os
import time
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import requests
from dotenv import load_dotenv
from sqlitedict import SqliteDict

# --- New data providers --------------------------------------------------
SSTATS_KEY = os.getenv("SSTATS_KEY")
SSTATS_BASE = "https://sstats.net/api/v1"
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/forecast"

# ---------------------------------------------------------------------
# конфигурация

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(ROOT, "apifootball_cache.sqlite")

load_dotenv()
API_KEY = os.getenv("APIFOOTBALL_KEY")
if not API_KEY:
    raise RuntimeError("API key is required – create .env with APIFOOTBALL_KEY=...")

BASE_URL = "https://v3.football.api-sports.io"
HEADERS = {"x-apisports-key": API_KEY}

# TTL кеша (сек) для разных эндпоинтов
TTL = {
    "fixtures":    6 * 3600,      # фикстуры обновляются раз в 6 ч
    "odds":        6 * 3600,
    "predictions": 6 * 3600,
}

# ---------------------------------------------------------------------
# внутренний доступ к кешу HTTP-ответов

_cache = SqliteDict(CACHE_FILE, autocommit=True)


def _cache_key(path: str, params: Dict[str, Any]) -> str:
    return f"{path}:" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))


def _get(path: str, params: Dict[str, Any], ttl: int) -> Any:
    key = _cache_key(path, params)
    now = time.time()
    if key in _cache:
        ts, data = _cache[key]
        if now - ts < ttl:
            return data
    resp = requests.get(f"{BASE_URL}/{path}", headers=HEADERS, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    _cache[key] = (now, data)
    return data


# ---------------------------------------------------------------------
# публичные функции API-Football

def get_fixtures(date: datetime) -> Dict[str, Any]:
    """Фикстуры на указанную дату (UTC)."""
    return _get(
        "fixtures",
        {"date": date.strftime("%Y-%m-%d"), "timezone": "UTC"},
        TTL["fixtures"],
    )


def get_odds(fixture_id: int) -> Dict[str, Any]:
    """Коэффициенты для конкретного матча."""
    return _get(
        "odds",
        {"fixture": fixture_id},
        TTL["odds"],
    )


def get_predictions(fixture_id: int) -> Dict[str, Any]:
    """Predictions-эндпоинт API-Football."""
    return _get(
        "predictions",
        {"fixture": fixture_id},
        TTL["predictions"],
    )


# ---------------------------------------------------------------------
# Fast-Screen: кэш Elo и получение формы команды

# инициализируем SQLite для кэша Elo
DB_PATH = os.getenv("BETAI_DB", os.path.join(ROOT, "betai_cache.db"))
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_cur = _conn.cursor()
_cur.execute("""
CREATE TABLE IF NOT EXISTS elo_daily (
    date TEXT,
    team_id INTEGER,
    elo REAL,
    PRIMARY KEY (date, team_id)
)
""")
_conn.commit()


def get_team_form(team_id: int, last_n: int = 10) -> list[dict[str, Any]]:
    """
    Возвращает список последних N матчей команды с базовыми метриками,
    чтобы оценить data_completeness.
    """
    data = _get(
        "fixtures",
        {"team": team_id, "last": last_n, "timezone": "UTC"},
        TTL["fixtures"],
    ).get("response", [])
    return data


def load_elo(team_id: int, date_str: str) -> float | None:
    """
    Загружает из кэша Elo команды на заданную дату (YYYY-MM-DD).
    """
    _cur.execute(
        "SELECT elo FROM elo_daily WHERE team_id = ? AND date = ?",
        (team_id, date_str),
    )
    row = _cur.fetchone()
    return row[0] if row else None


def save_elo(team_id: int, date_str: str, elo: float) -> None:
    """
    Сохраняет/обновляет Elo команды на заданную дату в кэше.
    """
    _cur.execute(
        "REPLACE INTO elo_daily (date, team_id, elo) VALUES (?, ?, ?)",
        (date_str, team_id, elo),
    )
    _conn.commit()


# ---------------------------------------------------------------------
# Additional data providers

def get_sstats(path: str, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Query sstats.net API."""
    if params is None:
        params = {}
    headers = {"Authorization": f"Bearer {SSTATS_KEY}"}
    resp = requests.get(f"{SSTATS_BASE}/{path}", headers=headers, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()


def get_weather(latitude: float, longitude: float) -> Dict[str, Any]:
    """Return weather forecast for given coordinates."""
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": "temperature_2m,wind_speed_10m,precipitation_probability",
    }
    resp = requests.get(OPEN_METEO_BASE, params=params, timeout=20)
    resp.raise_for_status()
    return resp.json()
