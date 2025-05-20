# ─────────────────────────────  app.py  ──────────────────────────────
"""Streamlit GUI for BetAI (v3.2) – динамический порог Edge."""

import os
from datetime import datetime
from typing import Dict, Tuple, List

import numpy as np
import pandas as pd
import streamlit as st

from betai.pipelines import quick_screen, detailed_analysis
from betai.models     import allocate_bank, Outcome          # уже были в старом коде
from betai.utils      import render_outcome

# ── Page config ───────────────────────────────────────────────────────
st.set_page_config(page_title="BetAI – Value Betting Scanner",
                   page_icon="⚽", layout="wide")
st.markdown("# ⚽ BetAI – Value Betting Scanner (v3.2)")

# ── API-ключ  ─────────────────────────────────────────────────────────
if not (st.secrets.get("APIFOOTBALL_KEY") or os.getenv("APIFOOTBALL_KEY")):
    st.error("Нужен ключ **APIFOOTBALL_KEY** в `.streamlit/secrets.toml` "
             "или как переменную окружения.")
    st.stop()

# ── Сайдбар: настройки пользователя ──────────────────────────────────
st.sidebar.header("Параметры сканирования")

today_only = st.sidebar.checkbox("Только сегодня", value=True)
days = 1 if today_only else st.sidebar.selectbox("Сканировать дней вперёд",
                                                 [1, 2, 3], index=0)

threshold_mode = st.sidebar.radio("Режим порога Edge",
                                  ["Динамический", "Статический"], index=0)
if threshold_mode == "Статический":
    edge_pct_static = st.sidebar.slider("Edge %, статический",
                                        1.0, 10.0, 4.0, 0.5)
else:
    st.sidebar.markdown("Динамический: верхняя треть результатов, "
                        "но **≥ 4 %**")

bank = st.sidebar.number_input("Банк, €",
                               min_value=10.0, value=1000.0,
                               step=50.0, format="%.2f")
top_n = st.sidebar.selectbox("Топ-лиг для анализа",
                             [10, 15, 20, 25, 30], index=0)
max_events = 30   # жёсткий лимит fast-этапа

# ── Кнопки-шаги ───────────────────────────────────────────────────────
col_btn = st.columns(3)
btn_fast  = col_btn[0].button("⚡ 1. Быстрый скрин",  use_container_width=True)
btn_deep  = col_btn[1].button("🔍 2. Глубокий анализ", use_container_width=True)
btn_stake = col_btn[2].button("💰 3. Рассчитать ставки",
                              use_container_width=True)

table_ph   = st.empty()
notice_ph  = st.empty()
metrics_ph = st.empty()

# ── Шаг-1: быстрый скрин ─────────────────────────────────────────────
if btn_fast:
    cand = quick_screen(days, top_n, max_events=max_events)
    st.session_state["fast_raw"] = cand

    # формируем DataFrame
    rows = []
    for i, c in enumerate(cand, 1):
        ts = datetime.fromtimestamp(c["fixture"]["timestamp"])
        rows.append(dict(
            No         = i,
            Use        = True,
            Date       = ts.date().isoformat(),
            Time       = ts.time().strftime("%H:%M"),
            League     = c["league"]["name"],
            Match      = c["teams"]["home"]["name"] + " – " +
                         c["teams"]["away"]["name"],
            side       = c["side"],
            p_est      = round(c["p_est"] * 100, 1),
            k_mean     = c["k_mean"],
            value_approx = round(c["value_approx"], 3),
            Flag       = c["league"]["flag"],
            Min_Odds   = None,
            Edge_pct   = None,
            Stake_eur  = 0,
        ))

    df_fast = pd.DataFrame(rows)[
        ["No", "Use", "Date", "Time", "League", "Match", "side",
         "p_est", "k_mean", "value_approx",
         "Min_Odds", "Edge_pct", "Stake_eur"]
    ]

    edited = table_ph.data_editor(
        df_fast,
        hide_index=True,
        column_config={
            "Use": st.column_config.CheckboxColumn(),
            "p_est": st.column_config.NumberColumn("p_est %", format="%.1f %"),
            "k_mean": st.column_config.NumberColumn("Avg Odds", format="%.3f"),
            "value_approx": st.column_config.NumberColumn("Value≈",
                                                          format="%.3f"),
        },
        use_container_width=True,
        key="fast_editor",
    )
    st.session_state["edited_d"] = edited
    st.session_state["deep_done"] = False
    notice_ph.info(f"Быстрый скрин: {len(df_fast)} событий")

# ── Шаг-2: глубокий анализ ───────────────────────────────────────────
if btn_deep:
    if "edited_d" not in st.session_state:
        st.warning("Сначала выполните быстрый скрин.")
        st.stop()

    df_e = st.session_state["edited_d"]
    raw  = st.session_state["fast_raw"]

    mask = df_e["Use"].tolist()
    kept = [r for r, m in zip(raw, mask) if m]

    if not kept:
        notice_ph.info("Глубокий анализ: ни одна строка не отмечена.")
        st.session_state["deep_map"]  = {}
        st.session_state["deep_done"] = True
        st.stop()

    # deep-этап сначала считает ВСЕ исходы (без фильтра)
    outs: List[Outcome] = detailed_analysis(kept, edge_min=None)

    # определяем порог
    edges = np.array([o.edge for o in outs])
    dyn_thr = max(0.04, np.percentile(edges, 66))   # ≥ 4 %
    if threshold_mode == "Динамический":
        edge_thr = dyn_thr
    else:
        edge_thr = edge_pct_static / 100

    outs = [o for o in outs if o.edge >= edge_thr]
    deep_map: Dict[Tuple[str, str], Outcome] = {
        (o.match, o.market): o for o in outs
    }

    st.session_state["deep_map"]  = deep_map
    st.session_state["deep_done"] = True
    notice_ph.success(
        f"Глубокий анализ вернул {len(outs)} исходов "
        f"(edge ≥ {edge_thr*100:.1f} %)"
    )

    # enrich table
    def enrich(row):
        key = (row["Match"], "1X2")      # пока анализируем только рынок 1X2
        o = deep_map.get(key)
        if o:
            row["Min_Odds"] = o.k_dec
            row["Edge_pct"] = round(o.edge * 100, 1)
            if o.edge < edge_thr:
                row["Use"] = False
        return row

    df_e = df_e.apply(enrich, axis=1)
    st.session_state["edited_d"] = df_e

    table_ph.dataframe(
        df_e,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Min_Odds": st.column_config.NumberColumn("Min Odds", format="%.3f"),
            "Edge_pct": st.column_config.NumberColumn("Edge %", format="%.1f %"),
        },
    )

    # разворачиваемые блоки
    st.markdown("## 📊 Детальный анализ")
    for o in outs:
        with st.expander(f"{o.match} – {o.pick_ru}"):
            st.markdown(render_outcome(o))

# ── Шаг-3: расчёт ставок ─────────────────────────────────────────────
if btn_stake:
    if not st.session_state.get("deep_done"):
        st.warning("Сначала выполните глубокий анализ.")
        st.stop()

    df_e = st.session_state["edited_d"]
    dmap = st.session_state["deep_map"]

    picks = [
        dmap[(row.Match, "1X2")]
        for row in df_e[df_e["Use"]].itertuples(index=False)
        if (row.Match, "1X2") in dmap
    ]

    if not picks:
        st.warning("Нет исходов для расчёта.")
        st.stop()

    allocate_bank(picks, bank)

    res = pd.DataFrame([{
        "Date":      o.date,
        "Time":      o.time,
        "League":    o.league,
        "Match":     o.match,
        "Pick":      o.pick_ru,
        "Min Odds":  o.k_dec,
        "Edge %":    round(o.edge * 100, 1),
        "Stake €":   int(round(o.stake_eur)),
    } for o in picks])

    cols = metrics_ph.columns(3)
    cols[0].metric("⌀ Min Odds", f"{res['Min Odds'].mean():.2f}")
    cols[1].metric("⌀ Edge %",  f"{res['Edge %'].mean():.1f} %")
    cols[2].metric("Σ Stake €", f"{res['Stake €'].sum()}",
                   delta=f"{len(res)} picks")

    st.dataframe(
        res,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Edge %": st.column_config.NumberColumn(format="%.1f %"),
        },
    )
