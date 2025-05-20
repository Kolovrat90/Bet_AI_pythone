import os
from datetime import datetime, date, time as dt_time, timezone
import streamlit as st
import pandas as pd

from betai.pipelines import quick_screen, detailed_analysis
from betai.models import allocate_bank

# ── page / constants ─────────────────────────────────────────────────────
st.set_page_config("BetAI – Value Betting Scanner (v3)", "⚽", layout="wide")
st.markdown("# ⚽ BetAI – Value Betting Scanner (v3)")

API_KEY = st.secrets.get("APIFOOTBALL_KEY") or os.getenv("APIFOOTBALL_KEY")
if not API_KEY:
    st.error("Нужен APIFOOTBALL_KEY (secrets.toml или env var)")
    st.stop()

# ── inputs ───────────────────────────────────────────────────────────────
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

# ── step-buttons ─────────────────────────────────────────────────────────
col1, col2, col3 = st.columns(3)

with col1:
    if st.button("⚡ 1. Быстрый скрин", type="primary"):
        st.session_state.clear()
        st.session_state["candidates"] = quick_screen(days, top_n)

with col2:
    if st.button(
        "🔍 2. Глубокий анализ",
        type="primary" if "candidates" in st.session_state else "secondary",
    ):
        raw = st.session_state.get("candidates", [])
        if raw:
            st.session_state.pop("candidates")
            # <<< главное изменение — edge_min = 0.0
            st.session_state["outs_raw"] = detailed_analysis(raw, 0.0)

with col3:
    if st.button(
        "💰 3. Рассчитать ставки",
        type="primary" if "outs_raw" in st.session_state else "secondary",
    ):
        st.session_state["do_calc"] = True

st.divider()

# ── helpers ──────────────────────────────────────────────────────────────
def empty_df(cols):      # пустая таблица с нужными колонками
    return pd.DataFrame([{c: None for c in cols}]).iloc[0:0]

def league_flag(league: dict) -> str:
    return league.get("logo", "") if league["name"].startswith("UEFA") else league.get("flag", "")

# ── show fast-screen table ───────────────────────────────────────────────
if "candidates" in st.session_state:
    rows = []
    for i, f in enumerate(st.session_state["candidates"], 1):
        ts = datetime.fromtimestamp(f["fixture"]["timestamp"], tz=timezone.utc)
        league = f["league"]
        rows.append(
            {
                "№": i, "Use": True,
                "Date": ts.date().isoformat(), "Time": ts.time().strftime("%H:%M"),
                "Flag": league_flag(league), "League": league["name"],
                "Match": f"{f['teams']['home']['name']} – {f['teams']['away']['name']}",
                "Side": f["side"],
                "p_est %": round(f["p_est"] * 100, 1),
                "Avg Odds": f["k_mean"], "Value≈": round(f["value_approx"], 3),
                "Stake €": 0,
            }
        )

    df_fast = pd.DataFrame(rows) if rows else empty_df(
        ["№", "Use", "Date", "Time", "Flag", "League", "Match",
         "Side", "p_est %", "Avg Odds", "Value≈", "Stake €"]
    )

    st.data_editor(
        df_fast, key="edited_q", hide_index=True, use_container_width=True,
        column_config={
            "Use": st.column_config.CheckboxColumn(),
            "Flag": st.column_config.ImageColumn("", width="small"),
            "p_est %":  st.column_config.NumberColumn(format="%.1f %"),
            "Avg Odds": st.column_config.NumberColumn(format="%.3f"),
            "Value≈":   st.column_config.NumberColumn(format="%.3f"),
            "Stake €":  st.column_config.NumberColumn(format="%d"),
        },
    )
    st.success(f"Быстрый скрин: найдено {len(rows)} событий")

# ── show deep-analysis table ─────────────────────────────────────────────
elif "outs_raw" in st.session_state:
    outs = st.session_state["outs_raw"]
    rows = []
    for i, o in enumerate(outs, 1):
        rows.append(
            {
                "№": i, "Use": True, "Flag": o.flag_url,
                "Date": o.date, "Time": o.time,
                "League": o.league, "Match": o.match, "Pick": o.pick_ru,
                "Min Odds": o.k_dec, "Edge %": round(o.edge * 100, 1), "Stake €": 0,
            }
        )
    df_deep = pd.DataFrame(rows) if rows else empty_df(
        ["№", "Use", "Flag", "Date", "Time", "League", "Match",
         "Pick", "Min Odds", "Edge %", "Stake €"]
    )

    st.data_editor(
        df_deep, key="edited_d", hide_index=True, use_container_width=True,
        column_config={
            "Use": st.column_config.CheckboxColumn(),
            "Flag": st.column_config.ImageColumn("", width="small"),
            "Min Odds": st.column_config.NumberColumn(format="%.2f"),
            "Edge %":   st.column_config.NumberColumn(format="%.1f %"),
            "Stake €":  st.column_config.NumberColumn(format="%d"),
        },
    )
    st.success(f"Глубокий анализ вернул {len(rows)} исходов (порог ещё не применён)")

# ── final kelly calc ─────────────────────────────────────────────────────
if st.session_state.get("do_calc") and "outs_raw" in st.session_state:
    st.session_state.pop("do_calc")

    edited = st.session_state.get("edited_d")
    if edited is None or edited.empty or "Use" not in edited.columns:
        st.warning("Отметьте события перед расчётом ставок")
        st.stop()

    mask = edited["Use"].tolist()
    kept = [o for o, m in zip(st.session_state["outs_raw"], mask) if m]
    # применяем пользовательский порог edge
    kept = [o for o in kept if o.edge >= edge_pct / 100.0]

    if not kept:
        st.warning("После фильтрации (edge ≥ порог) ничего не осталось")
        st.stop()

    allocate_bank(kept, bank)

    final_rows = []
    for i, o in enumerate(kept, 1):
        final_rows.append(
            {
                "№": i, "Date": o.date, "Time": o.time, "League": o.league,
                "Match": o.match,
                "Pick": o.pick_ru.replace("Победа хозяев", "Хозяева")
                                 .replace("Победа гостей", "Гости"),
                "Min Odds": o.k_dec, "Edge %": f"{o.edge*100:.1f} %",
                "Stake €": int(o.stake_eur),
            }
        )

    st.subheader("📋 Итоговые ставки")
    st.dataframe(
        pd.DataFrame(final_rows), hide_index=True, use_container_width=True,
        column_config={"Stake €": st.column_config.NumberColumn(format="%d")},
    )

    for o in kept:
        with st.expander(f"{o.league}: {o.match} → {o.pick_ru}, {int(o.stake_eur)}€"):
            st.json(
                {
                    "p_model": f"{o.p_model:.3f}",
                    "edge":    f"{o.edge*100:.1f} %",
                    "f_raw":   f"{o.f_raw:.3f}",
                    "f_final": f"{o.f_final:.3f}",
                },
                expanded=False,
            )
            st.bar_chart({"p_model": [o.p_model]})
