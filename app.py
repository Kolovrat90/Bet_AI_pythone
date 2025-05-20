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
    st.error("Нужен ключ APIFOOTBALL_KEY")
    st.stop()

# ── Inputs ────────────────────────────────────────────────────────────────
c0, c1, c2 = st.columns([1,2,2])
with c0:
    today_only = st.checkbox("Сегодня", True)
with c1:
    edge_pct = st.slider("Порог ценности, %", 1, 10, 5)
with c2:
    bank = st.number_input("Банк, €", 10.0, 100000.0, 1000.0, 50.0, "%.2f")

days  = 1 if today_only else st.selectbox("Сканировать дней вперёд", [1,2,3], 0)
top_n = st.selectbox("Топ-лиг для анализа", [10,15,20,25,30], 0)

# ── Последовательные кнопки ──────────────────────────────────────────────
b1, b2, b3 = st.columns(3)
with b1:
    if st.button("⚡ 1. Быстрый скрин", key="btn_q"):
        st.session_state.quick = True
        st.session_state.deep  = False
        st.session_state.calc  = False
with b2:
    if st.session_state.get("quick", False):
        if st.button("🔍 2. Глубокий анализ", key="btn_d"):
            st.session_state.deep = True
            st.session_state.calc = False
    else:
        st.button("🔍 2. Глубокий анализ", disabled=True)
with b3:
    if st.session_state.get("deep", False):
        if st.button("💰 3. Рассчитать ставки", key="btn_c"):
            st.session_state.calc = True
    else:
        st.button("💰 3. Расситать ставки", disabled=True)

# ── Плейсхолдеры для таблиц/метрик ────────────────────────────────────────
metrics_ph = st.empty()
table_q_ph = st.empty()
table_d_ph = st.empty()
table_f_ph = st.empty()

# ── Шаг 1: Быстрый скрин ────────────────────────────────────────────────────
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
            "Flag":      f["league"].get("flag", ""),               # URL флага
            "League":    f["league"]["name"],
            "Match":     f["teams"]["home"]["name"] + " – " +
                         f["teams"]["away"]["name"],
            "Side":      f["side"],
            "p_est %":   round(f["p_est"]*100,1),
            "Avg Odds":  f["k_mean"],
            "Value≈":    round(f["value_approx"],3),
            "Stake €":   0,
        })
    df_q = pd.DataFrame(rows)
    df_q["No"] = range(1, len(df_q)+1)

    table_q_ph.data_editor(
        df_q,
        hide_index=True,
        column_config={
            "No":       st.column_config.NumberColumn("№", format="%d", disabled=True),
            "Use":      st.column_config.CheckboxColumn(),
            "Flag":     st.column_config.ImageColumn("", width="small"),
            "p_est %":  st.column_config.NumberColumn(format="%.1f %"),
            "Avg Odds": st.column_config.NumberColumn(format="%.3f"),
            "Value≈":   st.column_config.NumberColumn(format="%.3f"),
            "Stake €":  st.column_config.NumberColumn(format="%d"),
        },
        use_container_width=True,
    )
    # очищаем возможные таблицы следующих шагов
    table_d_ph.empty()
    table_f_ph.empty()

# ── Шаг 2: Глубокий анализ ─────────────────────────────────────────────────
if st.session_state.get("deep", False):
    if "candidates" not in st.session_state:
        st.warning("Сначала выполните быстрый скрин")
    else:
        edited_q = table_q_ph._last_value  # получаем df из редактора
        mask = edited_q["Use"].tolist()
        raw  = st.session_state["candidates"]
        to_analyze = [c for c,m in zip(raw, mask) if m]

        if not to_analyze:
            st.warning("Нужно отметить хотя бы одно событие")
        else:
            outs = detailed_analysis(to_analyze, edge_pct/100.0)
            allocate_bank(outs, bank)
            st.session_state["outs_final"] = outs
            st.success(f"Глубокий анализ вернул {len(outs)} ставок")

            # покажем промежуточную таблицу deep
            rows = []
            for i, o in enumerate(outs, start=1):
                rows.append({
                    "No":       i,
                    "Date":     o.date,
                    "Time":     o.time,
                    "Flag":     getattr(o, "flag_url", ""),
                    "League":   o.league,
                    "Match":    o.match,
                    "Pick":     o.pick_ru,
                    "Edge %":   f"{o.edge*100:.1f} %",
                    "Stake €":  o.stake_eur,
                })
            df_d = pd.DataFrame(rows)
            table_d_ph.dataframe(df_d, use_container_width=True)

# ── Шаг 3: Рассчитать ставки ───────────────────────────────────────────────
if st.session_state.get("calc", False):
    if "outs_final" not in st.session_state:
        st.warning("Сначала выполните глубокий анализ")
    else:
        final = st.session_state["outs_final"]
        rows = []
        for i,o in enumerate(final, start=1):
            rows.append({
                "No":       i,
                "Date":     o.date,
                "Time":     o.time,
                "Flag":     getattr(o, "flag_url", ""),
                "League":   o.league,
                "Match":    o.match,
                "Pick":     o.pick_ru.replace("Победа хозяев","Хозяева")
                                         .replace("Победа гостей","Гости"),
                "Min Odds": o.k_dec,
                "Edge %":   round(o.edge*100,1),
                "Stake €":  o.stake_eur,
            })
        df_f = pd.DataFrame(rows)

        # метрики
        if not df_f.empty:
            cols = metrics_ph.columns(len(df_f.columns))
            cols[df_f.columns.get_loc("Min Odds")].metric("⌀ Min Odds", f"{df_f['Min Odds'].mean():.2f}")
            cols[df_f.columns.get_loc("Edge %")].metric("⌀ Edge %",    f"{df_f['Edge %'].mean():.1f} %")
            cols[df_f.columns.get_loc("Stake €")].metric("Σ Stake €",  f"{df_f['Stake €'].sum():.0f}")

        table_f_ph.dataframe(
            df_f,
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
