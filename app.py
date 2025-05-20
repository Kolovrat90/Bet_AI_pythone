import os
from datetime import datetime, date, time as dt_time
import streamlit as st
import pandas as pd

from betai.pipelines import scan_days
from betai.models import allocate_bank

# ── Page config ──────────────────────────────────────────────────────────
st.set_page_config(page_title="BetAI – Value Betting Scanner", page_icon="⚽", layout="wide")
st.markdown("# ⚽ BetAI – Value Betting Scanner (MVP)")

# ── API-ключ ──────────────────────────────────────────────────────────────
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

days = 1 if today_only else st.selectbox("Сканировать дней вперёд", [1, 2, 3], 0)
top_n = st.selectbox("Топ-лиг для анализа", [10, 15, 20, 25, 30], 0)

btn_scan = st.button("🔍 Сканировать матчи", type="primary")
btn_calc = st.button("💰 Рассчитать ставки")

# ── Cached scan ───────────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _scan(d, e, n):
    return scan_days(d, e, n)

# ── Шаг 1: сканирование ────────────────────────────────────────────────────
if btn_scan:
    outs = _scan(days, edge_pct / 100.0, top_n)
    st.session_state["outs_raw"] = outs
    st.success(f"Найдено {len(outs)} value-исходов (edge ≥ {edge_pct}%)")

# ── Шаг 2: редактор и результат в одном месте ──────────────────────────────
if "outs_raw" in st.session_state:
    outs = st.session_state["outs_raw"]

    # Собираем DataFrame и фильтруем уже сыгранные матчи
    df = pd.DataFrame(o.model_dump() for o in outs)
    now = datetime.now()
    df = df[df.apply(
        lambda r: datetime.combine(date.fromisoformat(r.date),
                                   dt_time.fromisoformat(r.time)) > now,
        axis=1
    )].reset_index(drop=True)

    # Добавляем колонку №, Use, служебные поля
    df.insert(0, "No", range(1, len(df) + 1))
    df.insert(1, "Use", True)
    df["Edge %"] = (df["edge"] * 100).round(1)
    df["Stake €"] = 0
    df["Flag"] = df["flag_url"]
    df = df.rename(columns={
        "date":    "Date", "time":    "Time",
        "league":  "League", "match":  "Match",
        "pick_ru": "Pick",   "k_dec":   "Min Odds"
    })
    view = df[["No", "Use", "Date", "Time", "Flag", "League", "Match", "Pick", "Min Odds", "Edge %", "Stake €"]]

    # Плейсхолдеры: один для метрик, второй для таблицы (редактора и результата)
    metrics_ph = st.empty()
    table_ph   = st.empty()

    # Редактируемый DataFrame
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

    # По нажатию «Рассчитать» — показываем метрики над таблицей и саму таблицу
    if btn_calc:
        mask = edited["Use"].tolist()
        kept = [o for o, u in zip(outs, mask) if u]

        if not kept:
            st.warning("Нечего рассчитывать — ни одна строка не отмечена.")
        else:
            # Аллокация банка
            allocate_bank(kept, bank)

            # Формируем итоговый DataFrame с нумерацией
            rows = []
            for o in kept:
                rows.append({
                    "Date":     o.date,
                    "Time":     o.time,
                    "Flag":     o.flag_url,
                    "League":   o.league,
                    "Match":    o.match,
                    "Pick":     o.pick_ru.replace("Победа хозяев", "Хозяева")
                                      .replace("Победа гостей", "Гости"),
                    "Min Odds": o.k_dec,
                    "Edge %":   f"{o.edge*100:.1f} %",
                    "Stake €":  int(round(o.stake_eur))
                })
            res_df = pd.DataFrame(rows)
            res_df.insert(0, "No", range(1, len(res_df) + 1))

            # Метрики над таблицей, выравнивание под нужными столбцами
            n_cols = len(res_df.columns)
            cols = metrics_ph.columns(n_cols)
            idx_min = res_df.columns.get_loc("Min Odds")
            idx_edge = res_df.columns.get_loc("Edge %")
            idx_stk  = res_df.columns.get_loc("Stake €")
            cols[idx_min].metric("⌀ Min Odds", f"{res_df['Min Odds'].mean():.2f}")
            avg_edge = res_df["Edge %"].str.rstrip(" %").astype(float).mean()
            cols[idx_edge].metric("⌀ Edge %", f"{avg_edge:.1f} %")
            cols[idx_stk].metric("Σ Stake €", f"{res_df['Stake €'].sum()}")

            # И сам итоговый DataFrame вместо редактора
            table_ph.dataframe(
                res_df,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Flag":    st.column_config.ImageColumn("", width="small"),
                    "Stake €": st.column_config.NumberColumn(format="%d"),
                },
            )
