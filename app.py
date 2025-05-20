import os, itertools
from datetime import datetime, timezone
from typing import Dict, Tuple, Optional

import pandas as pd
import streamlit as st

from betai.pipelines import quick_screen, detailed_analysis
from betai.models import Outcome, allocate_bank

# ────────── basic setup ──────────
st.set_page_config("BetAI – Value Betting Scanner (v3)", "⚽", layout="wide")
st.markdown("# ⚽ BetAI – Value Betting Scanner (v3)")

API_KEY = st.secrets.get("APIFOOTBALL_KEY") or os.getenv("APIFOOTBALL_KEY")
if not API_KEY:
    st.error("Нужен APIFOOTBALL_KEY (secrets.toml или переменная окружения)")
    st.stop()

# ────────── controls ──────────
c0, c1, c2 = st.columns([1, 2, 2])
with c0:
    today_only = st.checkbox("Сегодня", True)
with c1:
    edge_pct = st.slider("Порог ценности, %", 1, 10, 5)
with c2:
    bank = st.number_input("Банк, €", 10.0, step=50.0, value=1000.0, format="%.2f")

days  = 1 if today_only else st.selectbox("Сканировать дней вперёд", [1, 2, 3], 0)
top_n = st.selectbox("Топ-лиг для анализа", [10, 15, 20, 25, 30], 0)

st.divider()

# ────────── helpers ──────────
def flag_or_logo(league: Dict) -> str:
    return league.get("logo") or league.get("flag", "")

def stub_from_fast(row: pd.Series) -> Outcome:
    """создаём заглушку Outcome, если глубокий анализ не вернул запись"""
    return Outcome(
        fixture_id=row.fixture["id"],
        date=row.Date,
        time=row.Time,
        league=row.League,
        match=row.Match,
        market="1X2",
        pick_ru="Хозяева" if row.side == "Home" else "Гости",
        line=None,
        k_dec=row.k_mean,
        p_model=row["p_est %"]/100,
        flag_url=row.Flag,
    )

def key_from_row(row) -> Tuple[str, str]:
    """единый ключ (match, side) для Series и Outcome"""
    if isinstance(row, Outcome):
        side = ("Хозяева" if row.pick_ru.startswith("Победа хозяев")
                else "Гости" if row.pick_ru.startswith("Победа гостей")
                else row.pick_ru)
        return row.match, side
    # pandas Series / dict
    return row["Match"], row.get("Side") or row.get("side")

# ────────── buttons ──────────
b1, b2, b3 = st.columns(3)
with b1:
    if st.button("⚡ 1. Быстрый скрин", use_container_width=True):
        st.session_state.clear()
        st.session_state["fast"] = quick_screen(days, top_n)
with b2:
    if st.button("🔍 2. Глубокий анализ",
                 use_container_width=True,
                 disabled="fast" not in st.session_state):
        st.session_state["deep"] = detailed_analysis(st.session_state["fast"], 0.0)
with b3:
    if st.button("💰 3. Рассчитать ставки",
                 use_container_width=True,
                 disabled="fast" not in st.session_state):
        st.session_state["want_calc"] = True

st.divider()

# ────────── fast-table ──────────
if "fast" in st.session_state:
    # приводим fast-raw к удобному DataFrame
    rows = []
    for f in st.session_state["fast"]:
        ts = datetime.fromtimestamp(f["fixture"]["timestamp"], tz=timezone.utc)
        rows.append({
            "fixture": f["fixture"],
            "Flag":    flag_or_logo(f["league"]),
            "Date":    ts.date().isoformat(),
            "Time":    ts.time().strftime("%H:%M"),
            "League":  f["league"]["name"],
            "Match":   f["teams"]["home"]["name"] + " – " + f["teams"]["away"]["name"],
            "Side":    f["side"],
            "p_est %": round(f["p_est"]*100, 1),
            "k_mean":  f["k_mean"],
            "Value≈":  round(f["value_approx"], 3),
        })
    df = pd.DataFrame(rows)
    df.insert(0, "№",  range(1, len(df)+1))
    df.insert(2, "Use", True)

    # сливаем результаты deep-анализа, если он уже был
    if "deep" in st.session_state:
        deep_key_map = {key_from_row(o): o for o in st.session_state["deep"]}
        edge_vals = []
        for _, r in df.iterrows():
            o = deep_key_map.get(key_from_row(r))
            edge_vals.append(round(o.edge*100, 1) if o else None)
        df["Edge %"] = edge_vals
    else:
        df["Edge %"] = None

    df["Stake €"] = 0            # заполняется только после allocate

    show_cols = ["№","Use","Flag","Date","Time","League","Match","Side",
                 "k_mean","Value≈","Edge %","Stake €"]
    edited = st.data_editor(
        df[show_cols],
        key="table",
        hide_index=True,
        use_container_width=True,
        column_config={
            "Use":      st.column_config.CheckboxColumn(),
            "Flag":     st.column_config.ImageColumn("", width="small"),
            "k_mean":   st.column_config.NumberColumn("Avg Odds", format="%.3f"),
            "Value≈":   st.column_config.NumberColumn(format="%.3f"),
            "Edge %":   st.column_config.NumberColumn(format="%.1f"),
            "Stake €":  st.column_config.NumberColumn(format="%d"),
        },
    )

# ────────── calculate stakes ──────────
if st.session_state.pop("want_calc", False):

    if "table" not in st.session_state:
        st.warning("Сначала сделайте скрин / анализ")
        st.stop()

    df_ed: pd.DataFrame = st.session_state["table"]   # то, что пользователь видит
    kept_rows = df_ed[df_ed["Use"]]

    # карта (match, side) → Outcome из deep-анализа
    deep_map = {key_from_row(o): o for o in st.session_state.get("deep", [])}

    outs: list[Outcome] = []
    for _, r in kept_rows.iterrows():
        o = deep_map.get(key_from_row(r))
        if not o:
            o = stub_from_fast(r)
            o.edge = r["Value≈"] - 1          # approx-edge
        outs.append(o)

    # фильтр по edge-порогу
    outs = [o for o in outs if o.edge*100 >= edge_pct]
    if not outs:
        st.warning("После фильтра edge ничего не осталось")
        st.stop()

    allocate_bank(outs, bank)

    fin_df = pd.DataFrame([{
        "№": i+1, "Date": o.date, "Time": o.time,
        "League": o.league, "Match": o.match, "Pick": o.pick_ru,
        "Min Odds": o.k_dec, "Edge %": round(o.edge*100, 1),
        "Stake €": int(o.stake_eur)
    } for i, o in enumerate(outs)])

    st.subheader("📋 Итоговые ставки")
    st.dataframe(fin_df, hide_index=True, use_container_width=True,
                 column_config={"Stake €": st.column_config.NumberColumn(format="%d")})

