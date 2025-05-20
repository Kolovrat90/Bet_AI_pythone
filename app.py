import os
from datetime import datetime, date, time as dt_time, timezone
import streamlit as st
import pandas as pd

from betai.pipelines import quick_screen, detailed_analysis
from betai.models import allocate_bank

# ── Page config ──────────────────────────────────────────────────────────
st.set_page_config(
    page_title="BetAI – Value Betting Scanner (v3)",
    page_icon="⚽",
    layout="wide",
)
st.markdown("# ⚽ BetAI – Value Betting Scanner (v3)")

# ── API key ───────────────────────────────────────────────────────────────
API_KEY = st.secrets.get("APIFOOTBALL_KEY") or os.getenv("APIFOOTBALL_KEY")
if not API_KEY:
    st.error(
        "Нужен ключ APIFOOTBALL_KEY в .streamlit/secrets.toml "
        "или как переменную окружения."
    )
    st.stop()

# ── Inputs ────────────────────────────────────────────────────────────────
c0, c1, c2 = st.columns([1, 2, 2])
with c0:
    today_only = st.checkbox("Сегодня", True)
with c1:
    edge_pct = st.slider("Порог ценности, %", 1, 10, 5)
with c2:
    bank = st.number_input(
        "Банк, €",
        min_value=10.0,
        step=50.0,
        value=1000.0,
        format="%.2f",
    )

days = 1 if today_only else st.selectbox("Сканировать дней вперёд", [1, 2, 3], 0)
top_n = st.selectbox("Топ-лиг для анализа", [10, 15, 20, 25, 30], 0)

st.markdown("---")

# ── Шаги ─────────────────────────────────────────────────────────────────
col1, col2, col3 = st.columns([1, 1, 1])
with col1:
    if st.button(
        "⚡ 1. Быстрый скрин",
        type="primary" if "candidates" in st.session_state else "secondary",
    ):
        st.session_state.pop("outs_raw", None)
        st.session_state["candidates"] = quick_screen(days, top_n)
with col2:
    if st.button(
        "🔍 2. Глубокий анализ",
        type="primary" if "candidates" in st.session_state else "secondary",
    ):
        raw = st.session_state.get("candidates", [])
        st.session_state.pop("candidates", None)
        st.session_state["outs_raw"] = detailed_analysis(
            raw, edge_pct / 100.0
        )
with col3:
    if st.button(
        "💰 3. Рассчитать ставки",
        type="primary" if "outs_raw" in st.session_state else "secondary",
    ):
        # просто триггер, реальный расчёт — ниже
        pass

st.markdown("---")

# ── Отрисовка таблицы по шагу 1: быстрый скрин ────────────────────────────
if "candidates" in st.session_state:
    cands = st.session_state["candidates"]
    rows = []
    for i, f in enumerate(cands, start=1):
        ts = datetime.fromtimestamp(
            f["fixture"]["timestamp"], tz=timezone.utc
        )
        # логика флагов: только международные
        league = f["league"]
        if league["name"].startswith("UEFA"):
            flag = league.get("logo", "")
        else:
            flag = league.get("flag", "")
        rows.append(
            {
                "№": i,
                "Use": True,
                "Date": ts.date().isoformat(),
                "Time": ts.time().strftime("%H:%M"),
                "Flag": flag,
                "League": league["name"],
                "Match": f"{f['teams']['home']['name']} – {f['teams']['away']['name']}",
                "Side": f["side"],
                "p_est %": round(f["p_est"] * 100, 1),
                "Avg Odds": f["k_mean"],
                "Value≈": round(f["value_approx"], 3),
                "Stake €": 0,
            }
        )
    df_q = pd.DataFrame(rows)
    edited_q = st.data_editor(
        df_q,
        hide_index=True,
        column_config={
            "Use": st.column_config.CheckboxColumn(),
            "Flag": st.column_config.ImageColumn("", width="small"),
            "p_est %": st.column_config.NumberColumn(format="%.1f %"),
            "Avg Odds": st.column_config.NumberColumn(format="%.3f"),
            "Value≈": st.column_config.NumberColumn(format="%.3f"),
            "Stake €": st.column_config.NumberColumn(format="%d"),
        },
        use_container_width=True,
    )
    st.session_state["edited_q"] = edited_q

# ── Отрисовка таблицы по шагу 2: глубокий анализ ──────────────────────────
elif "outs_raw" in st.session_state:
    outs = st.session_state["outs_raw"]
    rows = []
    for i, o in enumerate(outs, start=1):
        rows.append(
            {
                "№": i,
                "Use": True,
                "Date": o.date,
                "Time": o.time,
                "Flag": o.flag_url,
                "League": o.league,
                "Match": o.match,
                "Pick": o.pick_ru,
                "Min Odds": o.k_dec,
                "Edge %": round(o.edge * 100, 1),
                "Stake €": 0,
            }
        )
    df_d = pd.DataFrame(rows)
    edited_d = st.data_editor(
        df_d,
        hide_index=True,
        column_config={
            "Use": st.column_config.CheckboxColumn(),
            "Flag": st.column_config.ImageColumn("", width="small"),
            "Min Odds": st.column_config.NumberColumn(format="%.2f"),
            "Edge %": st.column_config.NumberColumn(format="%.1f %"),
            "Stake €": st.column_config.NumberColumn(format="%d"),
        },
        use_container_width=True,
    )
    st.session_state["edited_d"] = edited_d

# ── Шаг 3: расчёт ставок и конечная таблица ────────────────────────────────
if "outs_raw" in st.session_state and "edited_d" in st.session_state:
    mask = st.session_state["edited_d"]["Use"].tolist()
    kept = [o for o, m in zip(st.session_state["outs_raw"], mask) if m]
    if kept:
        allocate_bank(kept, bank)
        final_rows = []
        for i, o in enumerate(kept, start=1):
            final_rows.append(
                {
                    "№": i,
                    "Date": o.date,
                    "Time": o.time,
                    "League": o.league,
                    "Match": o.match,
                    "Pick": o.pick_ru.replace("Победа хозяев", "Хозяева")
                                     .replace("Победа гостей", "Гости"),
                    "Min Odds": o.k_dec,
                    "Edge %": f"{o.edge*100:.1f} %",
                    "Stake €": int(o.stake_eur),
                }
            )
        st.markdown("### Итоговые ставки")
        st.dataframe(
            pd.DataFrame(final_rows),
            hide_index=True,
            use_container_width=True,
            column_config={
                "Stake €": st.column_config.NumberColumn(format="%d")
            },
        )
    else:
        st.warning("Нечего рассчитывать — ни одна строка не отмечена.")
