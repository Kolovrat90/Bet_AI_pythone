import os
from datetime import datetime, timezone
from typing import Dict, Tuple, Optional

import pandas as pd
import streamlit as st

from betai.pipelines import quick_screen, detailed_analysis
from betai.models import allocate_bank, Outcome

# ───────────────── page / env
st.set_page_config("BetAI – Value Betting Scanner (v3)", "⚽", layout="wide")
st.markdown("# ⚽ BetAI – Value Betting Scanner (v3)")

API_KEY = st.secrets.get("APIFOOTBALL_KEY") or os.getenv("APIFOOTBALL_KEY")
if not API_KEY:
    st.error("Нужен APIFOOTBALL_KEY (secrets.toml или env var)")
    st.stop()

# ───────────────── controls
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

# ───────────────── helpers
def flag_or_logo(league: Dict) -> str:
    return league.get("logo") if league["name"].startswith("UEFA") else league.get("flag", "")

def stub_from_fast(row: Dict) -> Outcome:
    """создаём заглушку Outcome, если deep-данных нет"""
    return Outcome(
        fixture_id=row["fixture"]["id"],
        date=row["Date"],
        time=row["Time"],
        league=row["League"],
        match=row["Match"],
        market="1X2",
        pick_ru=row["Side"],
        line=None,
        k_dec=row["Avg Odds"],
        p_model=row["p_est"]/100,
        flag_url=row["Flag"],
    )

# ───────────────── кнопки
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("⚡ 1. Быстрый скрин", use_container_width=True):
        st.session_state.clear()
        st.session_state["fast"] = quick_screen(days, top_n)
with col2:
    if st.button("🔍 2. Глубокий анализ",
                 use_container_width=True,
                 disabled="fast" not in st.session_state):
        st.session_state["deep"] = detailed_analysis(st.session_state["fast"], 0.0)
with col3:
    if st.button("💰 3. Рассчитать ставки",
                 use_container_width=True,
                 disabled="fast" not in st.session_state):
        st.session_state["do_calc"] = True

st.divider()

# ───────────────── таблица fast-screen
if "fast" in st.session_state:
    rows = []
    for f in st.session_state["fast"]:
        ts = datetime.fromtimestamp(f["fixture"]["timestamp"], tz=timezone.utc)
        league = f["league"]
        rows.append({
            **f,  # сохраняем оригинал для stub
            "№":    None,
            "Use":  True,
            "Flag": flag_or_logo(league),
            "Date": ts.date().isoformat(),
            "Time": ts.time().strftime("%H:%M"),
            "League": league["name"],
            "Match": f"{f['teams']['home']['name']} – {f['teams']['away']['name']}",
            "p_est": round(f["p_est"]*100, 1),
            "Value≈": round(f["value_approx"], 3),
            "Edge %": None,
            "Stake €": 0,
        })
    df = pd.DataFrame(rows)
    df["№"] = range(1, len(df)+1)

    # — merge deep edge (если уже есть)
    if "deep" in st.session_state:
        def _row_key(m, side):
            return (m, side)

        deep_map: Dict[Tuple[str, str], Outcome] = {
            _row_key(o.match,
                     "Хозяев" if o.pick_ru.startswith("Победа хозяев") else
                     "Гости"  if o.pick_ru.startswith("Победа гостей") else
                     o.pick_ru): o
            for o in st.session_state["deep"]
        }

        for i, r in df.iterrows():
            o = deep_map.get(_row_key(r["Match"], r["Side"]))
            if o:
                df.at[i, "Edge %"] = round(o.edge*100, 1)

    edited = st.data_editor(
        df,
        key="table",
        hide_index=True,
        use_container_width=True,
        column_config={
            "Use":      st.column_config.CheckboxColumn(),
            "Flag":     st.column_config.ImageColumn("", width="small"),
            "p_est":    st.column_config.NumberColumn("p_est %", format="%.1f"),
            "Avg Odds": st.column_config.NumberColumn(format="%.3f"),
            "Value≈":   st.column_config.NumberColumn(format="%.3f"),
            "Edge %":   st.column_config.NumberColumn(format="%.1f"),
            "Stake €":  st.column_config.NumberColumn(format="%d"),
        },
    )
else:
    st.info("Сначала сделайте «Быстрый скрин»")

# ───────────────── расчёт ставок
if st.session_state.get("do_calc"):
    st.session_state.pop("do_calc")

    if "table" not in st.session_state:
        st.warning("Нет таблицы для расчёта")
        st.stop()

    df_ed = st.session_state["table"]
    kept = [orig for orig, use in zip(st.session_state["fast"], df_ed["Use"]) if use]

    deep_map = { (o.match,
                  "Хозяев" if o.pick_ru.startswith("Победа хозяев") else
                  "Гости"  if o.pick_ru.startswith("Победа гостей") else
                  o.pick_ru): o
                 for o in st.session_state.get("deep", []) }

    outs: list[Outcome] = []
    for row in kept:
        key = (row["teams"]["home"]["name"] + " – " +
               row["teams"]["away"]["name"],
               row["side"])
        o = deep_map.get(key)
        if not o:
            o = stub_from_fast(row)
            o.edge = row["value_approx"] - 1
        outs.append(o)

    outs = [o for o in outs if o.edge >= edge_pct/100]
    if not outs:
        st.warning("После фильтра edge ничего не осталось")
        st.stop()

    allocate_bank(outs, bank)

    fin_df = pd.DataFrame([{
        "№": i+1, "Date": o.date, "Time": o.time, "League": o.league,
        "Match": o.match, "Pick": o.pick_ru,
        "Min Odds": o.k_dec, "Edge %": round(o.edge*100, 1),
        "Stake €": int(o.stake_eur)
    } for i, o in enumerate(outs)])

    st.subheader("📋 Итоговые ставки")
    st.dataframe(fin_df, hide_index=True, use_container_width=True,
                 column_config={"Stake €": st.column_config.NumberColumn(format="%d")})
