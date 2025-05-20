import os
from datetime import datetime, date, time as dt_time, timezone
import streamlit as st
import pandas as pd

from betai.pipelines import scan_days, quick_screen, detailed_analysis
from betai.models import allocate_bank

# ── Page config ──────────────────────────────────────────────────────────
st.set_page_config(page_title="BetAI – Value Betting Scanner", page_icon="⚽", layout="wide")
st.markdown("# ⚽ BetAI – Value Betting Scanner (v2)")

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

btn_scan  = st.button("🔍 Полный скан",   type="primary")
btn_quick = st.button("⚡ Быстрый скрин", type="secondary")
btn_calc  = st.button("💰 Рассчитать ставки")

# ── Cached full scan ──────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _full_scan(d, e, n):
    return scan_days(d, e, n)

# ── Шаг 1: полный скан ───────────────────────────────────────────────────
if btn_scan:
    outs = _full_scan(days, edge_pct/100.0, top_n)
    st.session_state["outs_raw"] = outs
    st.session_state.pop("candidates", None)
    st.success(f"Найдено {len(outs)} value-исходов (edge ≥ {edge_pct} %)")

# ── Шаг 1b: быстрый скрин ────────────────────────────────────────────────
if btn_quick:
    cands = quick_screen(days, top_n)
    st.session_state["candidates"] = cands
    st.session_state.pop("outs_raw", None)
    st.success(f"Найдено {len(cands)} кандидатов в быстрый скрин")

# ── Шаг 2: таблица для редактирования ────────────────────────────────────
if "outs_raw" in st.session_state or "candidates" in st.session_state:
    metrics_ph = st.empty()
    table_ph   = st.empty()

    # ======== Быстрый скрин =================================================
    if "candidates" in st.session_state:
        raw = st.session_state["candidates"]
        rows = []
        for f in raw:
            ts = datetime.fromtimestamp(f["fixture"]["timestamp"], tz=timezone.utc)
            rows.append({
                "No":        None,
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
        df = pd.DataFrame(rows)
        df["No"] = range(1, len(df)+1)
        view = df[["No","Use","Date","Time","League","Match","Side","p_est %","Avg Odds","Value≈"]]
        edited = table_ph.data_editor(
            view,
            hide_index=True,
            column_config={
                "Use":      st.column_config.CheckboxColumn(),
                "p_est %":  st.column_config.NumberColumn(format="%.1f %"),
                "Avg Odds": st.column_config.NumberColumn(format="%.3f"),
                "Value≈":   st.column_config.NumberColumn(format="%.3f"),
            },
            use_container_width=True,
        )
        st.session_state["edited"] = ("candidates", edited)

    # ======== Полный скан ====================================================
    else:
        outs = st.session_state["outs_raw"]
        df = pd.DataFrame(o.model_dump() for o in outs)

        # Вставляем вычисляемые поля
        df["edge"]      = [o.edge for o in outs]
        df["stake_eur"] = [o.stake_eur for o in outs]

        # Проверяем/добавляем flag_url
        if "flag_url" not in df.columns:
            df["flag_url"] = ""

        # Фильтруем прошлые матчи
        now = datetime.now()
        df = df[df.apply(
            lambda r: datetime.combine(date.fromisoformat(r.date),
                                       dt_time.fromisoformat(r.time)) > now,
            axis=1
        )].reset_index(drop=True)

        # Подготовка колонок
        df.insert(0, "No",  range(1, len(df)+1))
        df.insert(1, "Use", True)
        df["Edge %"]  = (df["edge"] * 100).round(1)
        df["Stake €"] = 0
        df["Flag"]    = df["flag_url"]

        df = df.rename(columns={
            "date":    "Date",  "time":   "Time",
            "league":  "League","match":  "Match",
            "pick_ru": "Pick",  "k_dec":  "Min Odds"
        })

        # === Обработка пустой таблицы ===
        expected_columns = [
            "No", "Use", "Date", "Time", "Flag", "League", "Match",
            "Pick", "Min Odds", "Edge %", "Stake €"
        ]
        if df.empty:
            df = pd.DataFrame(columns=expected_columns)

        view = df[expected_columns]
        edited = table_ph.data_editor(
            view,
            hide_index=True,
            column_config={
                "No":      st.column_config.NumberColumn("№", format="%d", disabled=True),
                "Use":     st.column_config.CheckboxColumn(),
                "Flag":    st.column_config.ImageColumn("", width="small"),
                "Edge %":  st.column_config.NumberColumn(format="%.1f %"),
                "Stake €": st.column_config.NumberColumn(format="%d"),
            },
            use_container_width=True,
        )
        st.session_state["edited"] = ("full", edited)

# ── Шаг 3: расчёт и вывод результатов ────────────────────────────────────
if btn_calc:
    if "edited" not in st.session_state:
        st.warning("Сначала выполните быстрый скрин или полный скан.")
        st.stop()

    mode, edited = st.session_state["edited"]
    if mode == "candidates":
        raw  = st.session_state["candidates"]
        mask = edited["Use"].tolist()
        kept = [c for c, m in zip(raw, mask) if m]
        if not kept:
            st.warning("Нечего рассчитывать — ни одна строка не отмечена.")
            st.stop()

        outs = detailed_analysis(kept, edge_pct/100.0)
    else:
        raw  = st.session_state["outs_raw"]
        mask = edited["Use"].tolist()
        outs = [o for o, m in zip(raw, mask) if m]

        if not outs:
            st.warning("Нечего рассчитывать — ни одна строка не отмечена.")
            st.stop()

    allocate_bank(outs, bank)

    # Строим финальную таблицу
    rows = []
    for i, o in enumerate(outs, 1):
        rows.append({
            "No":        i,
            "Date":      o.date,
            "Time":      o.time,
            "League":    o.league,
            "Match":     o.match,
            "Pick":      o.pick_ru.replace("Победа хозяев","Хозяева")
                                   .replace("Победа гостей","Гости"),
            "Min Odds":  o.k_dec,
            "Edge %":    round(o.edge*100, 1),
            "Stake €":   o.stake_eur,
        })
    df_fin = pd.DataFrame(rows)

    # Метрики
    if not df_fin.empty:
        cols = metrics_ph.columns(len(df_fin.columns))
        cols[df_fin.columns.get_loc("Min Odds")].metric("⌀ Min Odds", f"{df_fin['Min Odds'].mean():.2f}")
        cols[df_fin.columns.get_loc("Edge %")].metric("⌀ Edge %",    f"{df_fin['Edge %'].mean():.1f} %")
        cols[df_fin.columns.get_loc("Stake €")].metric("Σ Stake €",  f"{df_fin['Stake €'].sum():.0f}")

    table_ph.dataframe(
        df_fin,
        hide_index=True,
        use_container_width=True,
        column_config={"Stake €": st.column_config.NumberColumn(format="%d")},
    )

    # Детализация
    for o in outs:
        with st.expander(f"{o.league}: {o.match} → {o.pick_ru}, Stake {o.stake_eur} €"):
            st.write({
                "p_model": f"{o.p_model:.3f}",
                "edge":    f"{o.edge*100:.1f} %",
                "f_raw":   f"{o.f_raw:.3f}",
                "f_final": f"{o.f_final:.3f}",
            })
            st.bar_chart({"p_model": [o.p_model]})
