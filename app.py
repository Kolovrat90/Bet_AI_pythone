import os
from datetime import datetime, date, time as dt_time, timezone
import streamlit as st
import pandas as pd

from betai.pipelines import quick_screen, detailed_analysis
from betai.models import allocate_bank

# ── Page config ──────────────────────────────────────────────────────────
st.set_page_config(page_title="BetAI – Value Betting Scanner", page_icon="⚽", layout="wide")
st.markdown("# ⚽ BetAI – Value Betting Scanner (v3)")

# ── API key ───────────────────────────────────────────────────────────────
API_KEY = st.secrets.get("APIFOOTBALL_KEY") or os.getenv("APIFOOTBALL_KEY")
if not API_KEY:
    st.error("Нужен ключ APIFOOTBALL_KEY в .streamlit/secrets.toml или как переменную окружения.")
    st.stop()

# ── Inputs ────────────────────────────────────────────────────────────────
c0, c1, c2 = st.columns([1, 2, 2])
with c0:
    today_only = st.checkbox("Сегодня", True)
with c1:
    edge_pct = st.slider("Порог ценности, %", 1, 10, 5)
with c2:
    bank = st.number_input("Банк, €", min_value=10.0, step=50.0, value=1000.0, format="%.2f")

days  = 1 if today_only else st.selectbox("Сканировать дней вперёд", [1, 2, 3], 0)
top_n = st.selectbox("Топ-лиг для анализа", [10, 15, 20, 25, 30], 0)

# ── Action buttons ────────────────────────────────────────────────────────
# We place them in one row, and store their press in session_state
btn1, btn2, btn3 = st.columns(3)
with btn1:
    if st.button("⚡ 1. Быстрый скрин", key="btn_quick"):
        st.session_state.quick = True
        st.session_state.deep = False
        st.session_state.calc = False
with btn2:
    disabled_deep = not st.session_state.get("quick", False)
    if st.button("🔍 2. Глубокий анализ", key="btn_deep", disabled=disabled_deep):
        st.session_state.deep = True
        st.session_state.calc = False
with btn3:
    disabled_calc = not st.session_state.get("deep", False)
    if st.button("💰 3. Рассчитать ставки", key="btn_calc", disabled=disabled_calc):
        st.session_state.calc = True

# ── Step 1: Quick screen ───────────────────────────────────────────────────
if st.session_state.get("quick", False):
    cands = quick_screen(days, top_n)
    st.session_state["candidates"] = cands
    st.success(f"Быстрый скрин: найдено {len(cands)} событий")
    # show candidate table for selection
    rows = []
    for f in cands:
        ts = datetime.fromtimestamp(f["fixture"]["timestamp"], tz=timezone.utc)
        rows.append({
            "Use":       True,
            "Date":      ts.date().isoformat(),
            "Time":      ts.time().strftime("%H:%M"),
            "League":    f["league"]["name"],
            "Match":     f["teams"]["home"]["name"] + " – " + f["teams"]["away"]["name"],
            "Side":      f["side"],
            "p_est %":   round(f["p_est"]*100, 1),
            "Avg Odds":  f["k_mean"],
            "Value≈":    round(f["value_approx"], 3),
        })
    df_q = pd.DataFrame(rows)
    edited_q = st.data_editor(df_q, hide_index=True, column_config={
        "Use":      st.column_config.CheckboxColumn(),
        "p_est %":  st.column_config.NumberColumn(format="%.1f %"),
        "Avg Odds": st.column_config.NumberColumn(format="%.3f"),
        "Value≈":   st.column_config.NumberColumn(format="%.3f"),
    }, use_container_width=True)
    st.session_state["edited_q"] = edited_q

# ── Step 2: Detailed analysis ──────────────────────────────────────────────
if st.session_state.get("deep", False):
    if "edited_q" not in st.session_state:
        st.warning("Сначала выполните быстрый скрин")
    else:
        mask = st.session_state["edited_q"]["Use"].tolist()
        raw = st.session_state.get("candidates", [])
        to_analyze = [c for c, m in zip(raw, mask) if m]
        if not to_analyze:
            st.warning("Нужно отметить хотя бы одно событие")
        else:
            outs = detailed_analysis(to_analyze, edge_pct/100.0)
            allocate_bank(outs, bank)
            st.session_state["outs_final"] = outs
            st.success(f"Глубокий анализ выполнен: получено {len(outs)} ставок")

            # show interim table
            df_d = pd.DataFrame([{
                "Date":     o.date,
                "Time":     o.time,
                "League":   o.league,
                "Match":    o.match,
                "Pick":     o.pick_ru,
                "Edge %":   f"{o.edge*100:.1f}%",
                "Stake €":  o.stake_eur
            } for o in outs])
            st.dataframe(df_d, use_container_width=True)

# ── Step 3: Final calculation ──────────────────────────────────────────────
if st.session_state.get("calc", False):
    if "outs_final" not in st.session_state:
        st.warning("Сначала выполните глубокий анализ")
    else:
        final = st.session_state["outs_final"]
        # build final DataFrame with numbering
        rows = []
        for i, o in enumerate(final, start=1):
            rows.append({
                "No":       i,
                "Date":     o.date,
                "Time":     o.time,
                "League":   o.league,
                "Match":    o.match,
                "Pick":     o.pick_ru.replace("Победа хозяев","Хозяева").replace("Победа гостей","Гости"),
                "Min Odds": o.k_dec,
                "Edge %":   round(o.edge*100, 1),
                "Stake €":  o.stake_eur,
            })
        df_fin = pd.DataFrame(rows)
        # metrics
        c1, c2, c3, _ = st.columns([1,1,1,5])
        c1.metric("⌀ Min Odds", f"{df_fin['Min Odds'].mean():.2f}")
        c2.metric("⌀ Edge %",   f"{df_fin['Edge %'].mean():.1f} %")
        c3.metric("Σ Stake €",   f"{df_fin['Stake €'].sum()}")

        # final table
        st.dataframe(df_fin, use_container_width=True, column_config={
            "Stake €": st.column_config.NumberColumn(format="%d"),
        })

        # expanders
        for o in final:
            with st.expander(f"{o.league}: {o.match} → {o.pick_ru}, {o.stake_eur} €"):
                st.write({
                    "p_model": f"{o.p_model:.3f}",
                    "edge":    f"{o.edge*100:.1f}%",
                    "f_raw":   f"{o.f_raw:.3f}",
                    "f_final": f"{o.f_final:.3f}",
                })
                st.bar_chart({"p_model": [o.p_model]})
