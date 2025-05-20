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

# ── Step buttons ─────────────────────────────────────────────────────────
col_btns = st.columns([1,1,1])
with col_btns[0]:
    btn_quick = st.button("⚡ 1. Быстрый скрин", type="primary")
with col_btns[1]:
    btn_deep  = st.button("🔍 2. Глубокий анализ", type="secondary")
with col_btns[2]:
    btn_calc  = st.button("💰 3. Рассчитать ставки", type="secondary")

# placeholders
metrics_ph = st.empty()
table_ph   = st.empty()

# ── Шаг 1: Быстрый скрин ───────────────────────────────────────────────────
if btn_quick:
    cands = quick_screen(days, top_n)
    st.session_state["candidates"] = cands
    st.session_state.pop("outs_final", None)
    st.success(f"Быстрый скрин: найдено {len(cands)} кандидатов")
    
# ── Шаг 2: Глубокий анализ ───────────────────────────────────────────────
if btn_deep:
    if "candidates" not in st.session_state:
        st.warning("Сначала запустите Быстрый скрин")
    else:
        detailed = detailed_analysis(st.session_state["candidates"], edge_pct / 100.0)
        st.session_state["detailed"] = detailed
        st.session_state.pop("outs_final", None)
        st.success(f"Глубокий анализ вернул {len(detailed)} ставок")

# ── Шаг 3: Расчет ставок ──────────────────────────────────────────────────
if btn_calc:
    if "detailed" not in st.session_state:
        st.warning("Сначала выполните Глубокий анализ")
    else:
        allocate_bank(st.session_state["detailed"], bank)
        st.session_state["outs_final"] = st.session_state["detailed"]
        st.success("Ставки рассчитаны")

# ── Рендер единой таблицы с Edit & Expand ────────────────────────────────
if "candidates" in st.session_state:
    # формируем DataFrame из кандидатов (для Quick или Deep)
    if "detailed" in st.session_state:
        # используем detailed → Outcome[]
        raw = st.session_state["detailed"]
        rows = []
        for i, o in enumerate(raw, start=1):
            rows.append({
                "No":        i,
                "Use":       True,
                "Date":      o.date,
                "Time":      o.time,
                "Flag":      o.flag_url,
                "League":    o.league,
                "Match":     o.match,
                "Pick":      o.pick_ru,
                "Min Odds":  o.k_dec,
                "Edge %":    round(o.edge*100, 1),
                "Stake €":   int(o.stake_eur),
            })
        df = pd.DataFrame(rows)
        table_view = ["No","Use","Flag","Date","Time","League","Match","Pick","Min Odds","Edge %","Stake €"]
        table_ph.data_editor(
            df[table_view],
            hide_index=True,
            column_config={
                "Use":      st.column_config.CheckboxColumn(),
                "Flag":     st.column_config.ImageColumn("", width="small"),
                "Edge %":   st.column_config.NumberColumn(format="%.1f %"),
                "Stake €":  st.column_config.NumberColumn(format="%d"),
            },
            use_container_width=True
        )
        # Expanders: детализация по каждому исходу
        for o in raw:
            with st.expander(f"{o.league}: {o.match} → {o.pick_ru}, Stake {o.stake_eur} €"):
                st.markdown("**Вероятности и метрики:**")
                st.write({
                    "p_model": f"{o.p_model:.3f}",
                    "edge":    f"{o.edge*100:.1f}%",
                    "f_raw":   f"{o.f_raw:.3f}",
                    "f_final": f"{o.f_final:.3f}",
                })
                st.bar_chart([o.p_model])
        # Metrics summary
        if "outs_final" in st.session_state:
            final = st.session_state["outs_final"]
            df_fin = pd.DataFrame([{
                "Min Odds": o.k_dec,
                "Edge %":   o.edge*100,
                "Stake €":  o.stake_eur
            } for o in final])
            cols = metrics_ph.columns(3)
            cols[0].metric("⌀ Min Odds", f"{df_fin['Min Odds'].mean():.2f}")
            cols[1].metric("⌀ Edge %",   f"{df_fin['Edge %'].mean():.1f} %")
            cols[2].metric("Σ Stake €",   f"{df_fin['Stake €'].sum():.0f}")
    else:
        # пока только quick candidates:
        raw = st.session_state["candidates"]
        rows = []
        for idx, f in enumerate(raw, start=1):
            ts = datetime.fromtimestamp(f["fixture"]["timestamp"], tz=timezone.utc)
            league = f["league"]
            flag_url = league.get("logo") if league.get("name","").startswith("UEFA") else league.get("flag","")
            rows.append({
                "No":           idx,
                "Use":          True,
                "Date":         ts.date().isoformat(),
                "Time":         ts.time().strftime("%H:%M"),
                "Flag":         flag_url,
                "League":       league.get("name",""),
                "Match":        f["teams"]["home"]["name"] + " – " + f["teams"]["away"]["name"],
                "Side":         f["side"],
                "p_est %":      round(f["p_est"]*100, 1),
                "Avg Odds":     f["k_mean"],
                "Value≈":       round(f["value_approx"], 3),
                "Stake €":      0,
            })
        df = pd.DataFrame(rows)
        table_ph.data_editor(
            df[["No","Use","Flag","Date","Time","League","Match","Side","p_est %","Avg Odds","Value≈","Stake €"]],
            hide_index=True,
            column_config={
                "Use":      st.column_config.CheckboxColumn(),
                "Flag":     st.column_config.ImageColumn("", width="small"),
                "p_est %":  st.column_config.NumberColumn(format="%.1f %"),
                "Avg Odds": st.column_config.NumberColumn(format="%.3f"),
                "Value≈":   st.column_config.NumberColumn(format="%.3f"),
                "Stake €":  st.column_config.NumberColumn(format="%d"),
            },
            use_container_width=True
        )
