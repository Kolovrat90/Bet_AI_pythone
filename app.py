import os
from datetime import datetime, timezone
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

# ── Action buttons (in sequence) ─────────────────────────────────────────
b1, b2, b3 = st.columns(3)
with b1:
    if st.button("⚡ 1. Быстрый скрин", key="btn_q"):
        st.session_state.quick = True
        st.session_state.deep = False
        st.session_state.calc = False
with b2:
    deep_disabled = not st.session_state.get("quick", False)
    if st.button("🔍 2. Глубокий анализ", key="btn_d", disabled=deep_disabled):
        st.session_state.deep = True
        st.session_state.calc = False
with b3:
    calc_disabled = not st.session_state.get("deep", False)
    if st.button("💰 3. Рассчитать ставки", key="btn_c", disabled=calc_disabled):
        st.session_state.calc = True

# ── Placeholders ─────────────────────────────────────────────────────────
metrics_ph = st.empty()
table_ph   = st.empty()

# ── Step 1: Quick screen ─────────────────────────────────────────────────
if st.session_state.get("quick", False):
    cands = quick_screen(days, top_n)
    st.session_state["candidates"] = cands
    st.success(f"Быстрый скрин: найдено {len(cands)} событий")

    rows = []
    for f in cands:
        ts = datetime.fromtimestamp(f["fixture"]["timestamp"], tz=timezone.utc)
        rows.append({
            "No":        None,
            "Use":       True,
            "Date":      ts.date().isoformat(),
            "Time":      ts.time().strftime("%H:%M"),
            "Flag":      "",  # можно впоследствии подставить URL флага
            "League":    f["league"]["name"],
            "Match":     f["teams"]["home"]["name"] + " – " + f["teams"]["away"]["name"],
            "Side":      f["side"],
            "p_est %":   round(f["p_est"]*100, 1),
            "Avg Odds":  f["k_mean"],
            "Value≈":    round(f["value_approx"], 3),
            "Stake €":   0,
        })

    df_q = pd.DataFrame(rows)
    df_q["No"] = range(1, len(df_q) + 1)

    edited_q = table_ph.data_editor(
        df_q,
        hide_index=True,
        column_config={
            "No":      st.column_config.NumberColumn("№", format="%d", disabled=True),
            "Use":     st.column_config.CheckboxColumn(),
            "Flag":    st.column_config.ImageColumn("", width="small"),
            "p_est %": st.column_config.NumberColumn(format="%.1f %"),
            "Avg Odds":st.column_config.NumberColumn(format="%.3f"),
            "Value≈":  st.column_config.NumberColumn(format="%.3f"),
            "Stake €": st.column_config.NumberColumn(format="%d"),
        },
        use_container_width=True,
    )
    st.session_state["edited_q"] = edited_q

# ── Step 2: Detailed analysis ─────────────────────────────────────────────
if st.session_state.get("deep", False):
    if "edited_q" not in st.session_state:
        st.warning("Сначала выполните быстрый скрин")
    else:
        mask = st.session_state["edited_q"]["Use"].tolist()
        raw  = st.session_state["candidates"]
        to_analyze = [c for c, m in zip(raw, mask) if m]

        if not to_analyze:
            st.warning("Отметьте хотя бы одно событие для глубокого анализа")
        else:
            # проводим детальный анализ с заданным порогом
            outs = detailed_analysis(to_analyze, edge_pct/100.0)
            allocate_bank(outs, bank)
            st.session_state["outs_final"] = outs
            st.success(f"Глубокий анализ выполнен: получено {len(outs)} ставок")

            # промежуточный показ
            df_d = pd.DataFrame([{
                "No":       i+1,
                "Date":     o.date,
                "Time":     o.time,
                "Flag":     getattr(o, "flag_url", ""),
                "League":   o.league,
                "Match":    o.match,
                "Pick":     o.pick_ru,
                "Edge %":   f"{o.edge*100:.1f} %",
                "Stake €":  o.stake_eur
            } for i, o in enumerate(outs)])
            table_ph.dataframe(df_d, use_container_width=True)

# ── Step 3: Final calculation ─────────────────────────────────────────────
if st.session_state.get("calc", False):
    if "outs_final" not in st.session_state:
        st.warning("Сначала выполните глубокий анализ")
    else:
        final = st.session_state["outs_final"]

        rows = []
        for i, o in enumerate(final, start=1):
            rows.append({
                "No":       i,
                "Date":     o.date,
                "Time":     o.time,
                "Flag":     getattr(o, "flag_url", ""),
                "League":   o.league,
                "Match":    o.match,
                "Pick":     o.pick_ru.replace("Победа хозяев","Хозяева").replace("Победа гостей","Гости"),
                "Min Odds": o.k_dec,
                "Edge %":   round(o.edge*100,1),
                "Stake €":  o.stake_eur,
            })

        df_fin = pd.DataFrame(rows)

        # metrics above table
        if not df_fin.empty:
            cols = metrics_ph.columns(len(df_fin.columns))
            cols[df_fin.columns.get_loc("Min Odds")].metric("⌀ Min Odds", f"{df_fin['Min Odds'].mean():.2f}")
            cols[df_fin.columns.get_loc("Edge %")].metric("⌀ Edge %",    f"{df_fin['Edge %'].mean():.1f} %")
            cols[df_fin.columns.get_loc("Stake €")].metric("Σ Stake €",  f"{df_fin['Stake €'].sum():.0f}")

        st.dataframe(
            df_fin,
            use_container_width=True,
            column_config={"Stake €": st.column_config.NumberColumn(format="%d")},
        )

        # expanders
        for o in final:
            with st.expander(f"{o.league}: {o.match} → {o.pick_ru}, {o.stake_eur} €"):
                st.write({
                    "p_model": f"{o.p_model:.3f}",
                    "edge":    f"{o.edge*100:.1f} %",
                    "f_raw":   f"{o.f_raw:.3f}",
                    "f_final": f"{o.f_final:.3f}",
                })
                st.bar_chart({"p_model": [o.p_model]})
