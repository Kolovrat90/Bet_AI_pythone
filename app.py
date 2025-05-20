import os
from datetime import datetime, timezone
from typing import Dict, Tuple, Optional

import pandas as pd
import streamlit as st

from betai.pipelines import quick_screen, detailed_analysis
from betai.models import allocate_bank, Outcome

# ───────────────────────────────── page / env
st.set_page_config("BetAI – Value Betting Scanner (v3)", "⚽", layout="wide")
st.markdown("# ⚽ BetAI – Value Betting Scanner (v3)")

API_KEY = st.secrets.get("APIFOOTBALL_KEY") or os.getenv("APIFOOTBALL_KEY")
if not API_KEY:
    st.error("Нужен APIFOOTBALL_KEY (secrets.toml или env var)")
    st.stop()

# ───────────────────────────────── controls
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

# ───────────────────────────────── helper
def flag_or_logo(league: Dict) -> str:
    """UEFA → logo, остальные → flag"""
    return league.get("logo") if league["name"].startswith("UEFA") else league.get("flag", "")

def to_outcome_stub(i: int, row: Dict) -> Outcome:
    """Создаём «заглушку» Outcome, если detailed_analysis не смог вернуть данные"""
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
        p_model=row["p_est"] / 100,     # то, что было в fast-screen
        flag_url=row["Flag"],
    )

# ───────────────────────────────── buttons
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("⚡ 1. Быстрый скрин", use_container_width=True):
        st.session_state.clear()
        st.session_state["fast"] = quick_screen(days, top_n)
with col2:
    if st.button("🔍 2. Глубокий анализ",
                 use_container_width=True,
                 disabled="fast" not in st.session_state):
        fast = st.session_state.get("fast", [])
        st.session_state["deep"] = detailed_analysis(fast, 0.0)  # edge_min=0
with col3:
    if st.button("💰 3. Рассчитать ставки",
                 use_container_width=True,
                 disabled="fast" not in st.session_state):
        st.session_state["do_calc"] = True

st.divider()

# ───────────────────────────────── table build
if "fast" in st.session_state:
    fast_rows = []
    for i, f in enumerate(st.session_state["fast"], 1):
        ts = datetime.fromtimestamp(f["fixture"]["timestamp"], tz=timezone.utc)
        league = f["league"]
        fast_rows.append({
            "№": i, "Use": True, "Flag": flag_or_logo(league),
            "Date": ts.date().isoformat(), "Time": ts.time().strftime("%H:%M"),
            "League": league["name"],
            "Match": f"{f['teams']['home']['name']} – {f['teams']['away']['name']}",
            "Side": f["side"],
            "p_est": round(f["p_est"] * 100, 1),
            "Avg Odds": f["k_mean"],
            "Value≈":  round(f["value_approx"], 3),
            "Edge %": None,        # заполним после deep
            "Stake €": 0,
        })

    df = pd.DataFrame(fast_rows)

    # если deep уже есть → мержим
    if "deep" in st.session_state:
        # ключ = match+side
        def key(row: Outcome | Dict) -> Tuple[str, str]:
            return (row["Match"] if isinstance(row, dict) else row.match,
                    row["Side"]  if isinstance(row, dict) else
                    ("Хозяев" if row.pick_ru.startswith("Победа хозяев") else
                     "Гости"   if row.pick_ru.startswith("Победа гостей") else
                     row.pick_ru))

        deep_map: Dict[Tuple[str, str], Outcome] = {
            key(o): o for o in st.session_state["deep"]
        }
        for idx, r in df.iterrows():
            o: Optional[Outcome] = deep_map.get(key(r))
            if o:
                df.loc[idx, "Edge %"] = round(o.edge * 100, 1)

    # ——— editor ———
    edited = st.data_editor(
        df,
        key="table",
        hide_index=True,
        use_container_width=True,
        column_config={
            "Use": st.column_config.CheckboxColumn(),
            "Flag": st.column_config.ImageColumn("", width="small"),
            "p_est":  st.column_config.NumberColumn("p_est %", format="%.1f"),
            "Avg Odds": st.column_config.NumberColumn(format="%.3f"),
            "Value≈":   st.column_config.NumberColumn(format="%.3f"),
            "Edge %":   st.column_config.NumberColumn(format="%.1f"),
            "Stake €":  st.column_config.NumberColumn(format="%d"),
        },
    )
else:
    st.info("Сначала выполните «Быстрый скрин»")

# ───────────────────────────────── calc stakes
if st.session_state.get("do_calc"):
    st.session_state.pop("do_calc")
    if "table" not in st.session_state:
        st.warning("Сначала отсканируйте и отредактируйте таблицу")
        st.stop()

    df_ed = st.session_state["table"]
    kept_fast = [r for r, u in zip(df_ed.to_dict("records"), df_ed["Use"]) if u]

    # Outcomes из deep-анализа, либо заглушки
    deep_map = { (o.match, ("Хозяев" if o.pick_ru.startswith("Победа хозяев") else
                            "Гости"   if o.pick_ru.startswith("Победа гостей") else
                            o.pick_ru)): o
                 for o in st.session_state.get("deep", []) }

    outs: list[Outcome] = []
    for i, row in enumerate(kept_fast, 1):
        o = deep_map.get((row["Match"], row["Side"]))
        if not o:                # нет данных → stub
            o = to_outcome_stub(i, row)
            o.edge = row["Value≈"] - 1.0   # value≈ > 1 → edge≈
        outs.append(o)

    # фильтр по слайдеру edge
    outs = [o for o in outs if o.edge >= edge_pct / 100]
    if not outs:
        st.warning("После фильтра edge ничего не осталось")
        st.stop()

    allocate_bank(outs, bank)

    fin_df = pd.DataFrame([{
        "№": i, "Date": o.date, "Time": o.time, "League": o.league,
        "Match": o.match, "Pick": o.pick_ru,
        "Min Odds": o.k_dec, "Edge %": round(o.edge*100, 1),
        "Stake €": int(o.stake_eur),
    } for i, o in enumerate(outs, 1)])

    st.subheader("📋 Итоговые ставки")
    st.dataframe(fin_df, hide_index=True, use_container_width=True,
                 column_config={"Stake €": st.column_config.NumberColumn(format="%d")})
