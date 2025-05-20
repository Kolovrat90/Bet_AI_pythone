# ─────────────────────────────  app.py  ──────────────────────────────
import os
from datetime import datetime, date, time as dt_time, timezone
from typing import Dict, Tuple, List, Optional

import pandas as pd
import streamlit as st

from betai.pipelines import quick_screen, detailed_analysis
from betai.models     import allocate_bank, Outcome

# ── Page config ───────────────────────────────────────────────────────
st.set_page_config(
    page_title="BetAI – Value Betting Scanner",
    page_icon="⚽",
    layout="wide",
)
st.markdown("# ⚽ BetAI – Value Betting Scanner (v3.1)")

# ── API-ключ  ─────────────────────────────────────────────────────────
if not (st.secrets.get("APIFOOTBALL_KEY") or os.getenv("APIFOOTBALL_KEY")):
    st.error(
        "Нужен ключ **APIFOOTBALL_KEY** в `.streamlit/secrets.toml` "
        "или как переменную окружения."
    )
    st.stop()

# ── Пользовательские настройки ───────────────────────────────────────
c0, c1, c2 = st.columns([1, 2, 2])
with c0:
    today_only = st.checkbox("Сегодня", True)
with c1:
    edge_pct = st.slider("Порог ценности, %", 1, 10, 5)
with c2:
    bank = st.number_input("Банк, €", 10.0, step=50.0, value=1_000.0, format="%.2f")

days      = 1 if today_only else st.selectbox("Сканировать дней вперёд", [1, 2, 3], 0)
top_n     = st.selectbox("Топ-лиг для анализа", [10, 15, 20, 25, 30], 0)
max_events = 30                         # <- жёстный лимит верхушки

# ── Кнопки-этапы ──────────────────────────────────────────────────────
col_btn = st.columns(3)
btn_fast  = col_btn[0].button("⚡ 1. Быстрый скрин",   use_container_width=True)
btn_deep  = col_btn[1].button("🔍 2. Глубокий анализ", use_container_width=True)
btn_stake = col_btn[2].button("💰 3. Рассчитать ставки", use_container_width=True)

# ── Вспомогательные плейсхолдеры ─────────────────────────────────────
table_ph   = st.empty()
notice_ph  = st.empty()
metrics_ph = st.empty()

# ── Шаг-1  Быстрый скрин ─────────────────────────────────────────────
if btn_fast:
    st.session_state.pop("deep_map", None)
    fast = quick_screen(
        days,
        top_n,
        max_events=max_events,          # ← лимит 30
    )
    st.session_state["fast_raw"] = fast
    notice_ph.success(f"Быстрый скрин: найдено {len(fast)} событий")

    # --- превращаем в DataFrame для редактора
    rows: List[Dict] = []
    for i, f in enumerate(fast, 1):
        ts = datetime.fromtimestamp(f["fixture"]["timestamp"], tz=timezone.utc)
        league = f["league"]
        # flag/логотип
        flag_url = (
            league.get("logo", "")
            if league["name"].startswith("UEFA")
            else league.get("flag", "")
        )
        rows.append(
            dict(
                side       = f["side"],
                p_est      = round(f["p_est"] * 100, 1),
                k_mean     = f["k_mean"],
                value_approx = round(f["value_approx"], 3),
                №          = i,
                Use        = True,
                Flag       = flag_url,
                Date       = ts.date().isoformat(),
                Time       = ts.time().strftime("%H:%M"),
                League     = league["name"],
                Match      = f["teams"]["home"]["name"] + " – " +
                             f["teams"]["away"]["name"],
                Min_Odds   = None,         # заполняется позже
                Edge_pct   = None,
                Stake_eur  = 0,
            )
        )
    df_fast = pd.DataFrame(rows)

    # редактор
    edited = table_ph.data_editor(
        df_fast,
        hide_index=True,
        num_rows="dynamic",
        column_config={
            "Use":        st.column_config.CheckboxColumn(),
            "Flag":       st.column_config.ImageColumn("", width="small"),
            "p_est":      st.column_config.NumberColumn("p_est %", format="%.1f %"),
            "k_mean":     st.column_config.NumberColumn("Avg Odds", format="%.3f"),
            "value_approx": st.column_config.NumberColumn("Value≈", format="%.3f"),
        },
        use_container_width=True,
        key="fast_editor",
    )
    st.session_state["edited_d"]  = edited
    st.session_state["deep_done"] = False

# ── Шаг-2  Глубокий анализ ────────────────────────────────────────────
if btn_deep:
    if "edited_d" not in st.session_state:
        st.warning("Сначала выполните быстрый скрин.")
        st.stop()

    df_e = st.session_state["edited_d"]
    raw  = st.session_state["fast_raw"]

    # маска «Use»
    if "Use" not in df_e.columns:
        st.error("В таблице нет колонки **Use**.")
        st.stop()
    mask = df_e["Use"].tolist()
    kept = [r for r, m in zip(raw, mask) if m]

    if not kept:
        notice_ph.info("Глубокий анализ: ни одна строка не отмечена.")
        st.session_state["deep_map"]  = {}
        st.session_state["deep_done"] = True
        st.stop()

    # deep-stage
    outs: List[Outcome] = detailed_analysis(kept, edge_pct / 100.0)
    deep_map: Dict[Tuple[str, str], Outcome] = {
        (o.match, o.pick_ru.split(" ")[-1]): o for o in outs
    }
    st.session_state["deep_map"]  = deep_map
    st.session_state["deep_done"] = True
    notice_ph.success(f"Глубокий анализ вернул {len(outs)} исходов "
                      f"(порог уже применён)")

    # обновляем таблицу Edge / Min-odds
    def enrich(row):
        key = (row["Match"], row["side"])
        o   = deep_map.get(key)
        if o:
            row["Min_Odds"] = o.k_dec
            row["Edge_pct"] = round(o.edge * 100, 1)
        return row

    df_e = df_e.apply(enrich, axis=1)
    st.session_state["edited_d"] = df_e  # overwrite

    table_ph.dataframe(
        df_e,
        hide_index=True,
        use_container_width=True,
        column_config={
            "Flag":      st.column_config.ImageColumn("", width="small"),
            "Min_Odds":  st.column_config.NumberColumn("Min Odds", format="%.3f"),
            "Edge_pct":  st.column_config.NumberColumn("Edge %",   format="%.1f %"),
            "Stake_eur": st.column_config.NumberColumn("Stake €", format="%d"),
        },
    )

# ── Шаг-3  Расчёт ставок ─────────────────────────────────────────────
if btn_stake:
    if not st.session_state.get("deep_done"):
        st.warning("Сначала выполните глубокий анализ.")
        st.stop()

    df_e  = st.session_state["edited_d"]
    dmap  = st.session_state["deep_map"]

    mask = df_e["Use"].tolist()
    picks: List[Outcome] = []
    for row in df_e.itertuples(index=False):
        key = (row.Match, row.side)
        o   = dmap.get(key)
        if o and mask[row._asdict()["№"] - 1]:
            picks.append(o)

    if not picks:
        st.warning("Нет исходов для расчёта.")
        st.stop()

    allocate_bank(picks, bank)

    # окончательная таблица
    res = pd.DataFrame([{
        "№":        i + 1,
        "Date":     o.date,
        "Time":     o.time,
        "League":   o.league,
        "Match":    o.match,
        "Pick":     o.pick_ru,
        "Min Odds": o.k_dec,
        "Edge %":   round(o.edge * 100, 1),
        "Stake €":  int(round(o.stake_eur)),
    } for i, o in enumerate(picks)])

    # метрики
    cols = metrics_ph.columns(3)
    cols[0].metric("⌀ Min Odds", f"{res['Min Odds'].mean():.2f}")
    cols[1].metric("⌀ Edge %",   f"{res['Edge %'].mean():.1f} %")
    cols[2].metric("Σ Stake €",  f"{res['Stake €'].sum():.0f}")

    table_ph.dataframe(
        res,
        hide_index=True,
        use_container_width=True,
    )
# ───────────────────────────────────────────────────────────────────────
