from __future__ import annotations
from typing import Dict, List
from .markets_ru import MATCH_WINNER, ru_total, ru_ah

def parse_odds(data: Dict) -> List[Dict]:
    res: List[Dict] = []
    bk = data["response"][0]["bookmakers"] if data["response"] else []
    if not bk:
        return res

    for bet in bk[0]["bets"]:
        name = bet["name"]

        if name == "Match Winner":
            for v in bet["values"]:
                side = v["value"]  # Home / Draw / Away
                res.append(
                    dict(
                        market="1X2",
                        pick_ru=MATCH_WINNER[side],
                        line=None,
                        side=side,
                        k_dec=float(v["odd"]),
                    )
                )

        elif name == "Goals":
            for v in bet["values"]:
                side, line = v["value"].split(" ")
                res.append(
                    dict(
                        market="Total",
                        pick_ru=ru_total(float(line), side),
                        line=float(line),
                        side=side,
                        k_dec=float(v["odd"]),
                    )
                )

        elif name == "Asian Handicap":
            for v in bet["values"]:
                side, raw_line = v["value"].split(" ")
                res.append(
                    dict(
                        market="AH",
                        pick_ru=ru_ah(float(raw_line), side),
                        line=float(raw_line),
                        side=side,
                        k_dec=float(v["odd"]),
                    )
                )
    return res
