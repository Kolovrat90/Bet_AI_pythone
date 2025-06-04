"""Simple journal module for logging picks and updating results."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Any
from datetime import datetime


@dataclass
class LoggedPick:
    id: str
    loggedDate: str
    marketType: str
    outcomeSide: str
    k_off: float
    stake: float
    matchId: int
    status: str = "PENDING"
    actualResult: str | None = None
    finalScore: Dict[str, int] | None = None
    report_md: str | None = None


def log_picks(storage: List[LoggedPick], picks: List[Dict[str, Any]]) -> None:
    """Append unique picks for today to storage."""
    today = datetime.utcnow().date().isoformat()
    existing = {p.id for p in storage if p.loggedDate.startswith(today)}
    for p in picks:
        if p["id"] in existing:
            continue
        storage.append(
            LoggedPick(
                id=p["id"],
                loggedDate=datetime.utcnow().isoformat(),
                marketType=p["market"],
                outcomeSide=p["side"],
                k_off=p["k_dec"],
                stake=p.get("stake", 0.0),
                matchId=p["fixture_id"],
                report_md=p.get("report"),
            )
        )


def update_results(storage: List[LoggedPick], fetch_func) -> None:
    """Update PENDING picks using callback fetch_func(matchId) -> score dict."""
    for rec in storage:
        if rec.status != "PENDING":
            continue
        info = fetch_func(rec.matchId)
        if not info:
            continue
        rec.finalScore = info.get("goals")
        rec.actualResult = info.get("result")
        rec.status = info.get("status", "VOID")
