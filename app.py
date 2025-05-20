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

days = 1 if today_only else st.selectbox("Сканировать дней вперёд", [1, 2, 3], 0)
top_n = st.selectbox("Топ-лиг для анализа", [10, 15, 20, 25, 30], 0)

btn_scan  = st.button("🔍 Полный скан", type="primary")
btn_quick = st.button("⚡ Быстрый скрин", type="secondary")
btn_calc  = st.button("💰 Рассчитать ставки")

# ── Cached full scan ───────────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _full_scan(d, e, n):
    return scan_days(d, e, n)

# ── Step 1: Full scan ─────────────────────────────────────────────────────
if btn_scan:
    outs = _full_scan(days, edge_pct/100.0, top_n)
    st.session_state["outs_raw"] = outs
    st.session_state.pop("candidates", None)
    st.success(f"Найдено {len(outs)} value-исходов (edge ≥ {edge_pct}%)")

# ── Step 1b: Quick screen ─────────────────────────────────────────────────
if btn_quick:
    cands = quick_screen(days, top_n)
    st.session_state["candidates"] = cands
    st.session_state.pop("outs_raw", None)
    st.success(f"Найдено {len(cands)} кандидатов в быстрый скрин")

# ── Step 2: Show editable table ────────────────────────────────────────────
if "outs_raw" in st.session_state or "candidates" in st.session_state:
    metrics_ph = st.empty()
    table_ph   = st.empty()

    if "candidates" in st.session_state:
        raw = st.session_state["candidates"]
        # build DataFrame for quick-screen candidates
        rows = []
        for f in raw:
            # f is dict with keys: fixture, teams, league, side, p_est, k_mean, value_approx
            ts = datetime.fromtimestamp(f["fixture"]["timestamp"], tz=timezone.utc)
            rows.append({
                "No":             None,
                "Use":            True,
                "Date":           ts.date().isoformat(),
                "Time":           ts.time().strftime("%H:%M"),
                "League":         f["league"]["name"],
                "Match":          f["teams"]["home"]["name"] + " – " + f["teams"]["away"]["name"],
                "Side":           f["side"],
                "p_est":          round(f["p_est"]*100, 1),
                "k_mean":         f["k_mean"],
                "value_approx":   round(f["value_approx"], 3),
            })
        df = pd.DataFrame(rows)
        df["No"] = range(1, len(df)+1)
        view = df[["No","Use","Date","Time","League","Match","Side","p_est","k_mean","value_approx"]]
        edited = table_ph.data_editor(
            view,
            hide_index=True,
            column_config={
                "Use":          st.column_config.CheckboxColumn(),
                "p_est":        st.column_config.NumberColumn("p_est %", format="%.1f %"),
                "k_mean":       st.column_config.NumberColumn("Avg Odds", format="%.3f"),
                "value_approx": st.column_config.NumberColumn("Value≈", format="%.3f"),
            },
            use_container_width=True,
        )
        st.session_state["edited"] = ("candidates", edited)

    else:
        # full-scan flow
        outs = st.session_state["outs_raw"]
        df = pd.DataFrame(o.model_dump() for o in outs)
        now = datetime.now()
        df = df[df.apply(
            lambda r: datetime.combine(date.fromisoformat(r.date),
                                       dt_time.fromisoformat(r.time)) > now,
            axis=1
        )].reset_index(drop=True)
        df.insert(0, "No", range(1, len(df)+1))
        df.insert(1, "Use", True)
        df["Edge %"] = (df["edge"]*100).round(1)
        df["Stake €"] = 0
        df["Flag"] = df["flag_url"]
        df = df.rename(columns={
            "date":"Date","time":"Time","league":"League",
            "match":"Match","pick_ru":"Pick","k_dec":"Min Odds"
        })
        view = df[["No","Use","Date","Time","Flag","League","Match","Pick","Min Odds","Edge %","Stake €"]]
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

# ── Step 3: Calculate and show results ──────────────────────────────────────
if btn_calc:
    if "edited" not in st.session_state:
        st.warning("Сначала выполните быстрый скрин или полный скан.")
    else:
        mode, edited = st.session_state["edited"]
        if mode == "candidates":
            raw = st.session_state["candidates"]
            df_ed = edited
            mask = df_ed["Use"].tolist()
            kept = [c for c, m in zip(raw, mask) if m]
            if not kept:
                st.warning("Нечего рассчитывать — ни одна строка не отмечена.")
            else:
                # detailed analysis + allocate
                detailed = detailed_analysis(kept, edge_pct/100.0)
                allocate_bank(detailed, bank)
                final = detailed

        else:  # full scan flow
            raw = st.session_state["outs_raw"]
            df_ed = edited
            mask = df_ed["Use"].tolist()
            kept = [o for o, m in zip(raw, mask) if m]
            if not kept:
                st.warning("Нечего рассчитывать — ни одна строка не отмечена.")
                final = []
            else:
                allocate_bank(kept, bank)
                final = kept

        # display final table + expanders
        if final:
            # metrics
            df_fin = pd.DataFrame([{
                "No":         i+1,
                "Date":       o.date,
                "Time":       o.time,
                "League":     o.league,
                "Match":      o.match,
                "Pick":       o.pick_ru.replace("Победа хозяев","Хозяева")
                                      .replace("Победа гостей","Гости"),
                "Min Odds":   o.k_dec,
                "Edge %":     o.edge*100,
                "Stake €":    o.stake_eur
            } for i, o in enumerate(final)])
            df_fin_display = df_fin.copy()
            df_fin_display["Edge %"] = df_fin_display["Edge %"].round(1)
            df_fin_display.insert(0, "No", range(1, len(df_fin_display)+1))

            # metrics above table
            cols = metrics_ph.columns(len(df_fin_display.columns))
            idx_min = df_fin_display.columns.get_loc("Min Odds")
            idx_edge = df_fin_display.columns.get_loc("Edge %")
            idx_stk  = df_fin_display.columns.get_loc("Stake €")
            cols[idx_min].metric("⌀ Min Odds", f"{df_fin_display['Min Odds'].mean():.2f}")
            cols[idx_edge].metric("⌀ Edge %", f"{df_fin_display['Edge %'].mean():.1f} %")
            cols[idx_stk].metric("Σ Stake €", f"{df_fin_display['Stake €'].sum():.0f}")

            # table
            table_ph.dataframe(
                df_fin_display,
                hide_index=True,
                use_container_width=True,
                column_config={
                    "Stake €": st.column_config.NumberColumn(format="%d"),
                },
            )

            # expanders per outcome
            for o in final:
                with st.expander(f"{o.league}: {o.match} → {o.pick_ru}, Stake {o.stake_eur}€"):
                    st.markdown("**Вероятности:**")
                    st.write({
                        "p_model": f"{o.p_model:.3f}",
                        "edge":    f"{o.edge*100:.1f}%",
                        "f_raw":   f"{o.f_raw:.3f}",
                        "f_final": f"{o.f_final:.3f}",
                    })
                    # bar chart of probabilities if available
                    if hasattr(o, "p_model"):
                        st.bar_chart({"p_model": [o.p_model]})
        # end if final
