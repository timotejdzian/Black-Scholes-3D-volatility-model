# app.py
"""
Streamlit shell around the bs/ package. Run with:  streamlit run app.py
The UI stays dumb: inputs -> bs.* functions -> render figure.

Layout is two-phase so panels stay aligned: a controls row (bordered, labeled
per panel) is rendered and evaluated first, then all charts are rendered in a
second row at the same height regardless of how many control widgets each
panel needed. Sidebar settings are global and labeled as such.
"""
import contextlib
import io
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from bs.black_scholes import add_iv, anchor_to_forward, prepare_quotes, stitch_otm
from bs.dolt_data import get_historical_option_data
from bs.get_data import DEFAULT_R, get_option_data
from bs.visualisation import visualize

st.set_page_config(page_title="BS IV Surface", layout="wide")
st.title("Black-Scholes IV surface")


# ---------- cached data layer ----------

@st.cache_data(ttl=600, show_spinner="Fetching live chain from yfinance...")
def load_live(symbol):
    S, r, calls_df, puts_df = get_option_data(symbol)
    return S, calls_df, puts_df


@st.cache_data(show_spinner="Fetching historical chains (first load per ticker is slow)...")
def load_hist(symbol, start_iso, end_iso):
    return get_historical_option_data(symbol, date.fromisoformat(start_iso), date.fromisoformat(end_iso))


@st.cache_data(show_spinner="Solving IV...")
def compute_surface(calls_df, puts_df, S, r, q, mode, use_last_fallback,
                    moneyness_range, t_range):
    """Cached so plot rotation / log toggling never re-runs brentq.
    Returns (surface_df, captured_log)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        kwargs = dict(S=S, use_last_fallback=use_last_fallback,
                      moneyness_range=moneyness_range, t_range=t_range)
        if mode in ("calls", "stitched OTM"):
            calls_df = add_iv(prepare_quotes(calls_df, **kwargs), S, r, "call", q)
        if mode in ("puts", "stitched OTM"):
            puts_df = add_iv(prepare_quotes(puts_df, **kwargs), S, r, "put", q)

        if mode == "calls":
            surface = calls_df
        elif mode == "puts":
            surface = puts_df
        else:
            surface = stitch_otm(calls_df, puts_df)
    return surface, buf.getvalue()


# ---------- global controls (sidebar applies to ALL panels) ----------

with st.sidebar:
    st.header("Global settings")
    st.caption("Everything in this sidebar applies to all panels. "
               "Per-panel choices (source, ticker, mode, dates) live in each panel's box.")
    st.subheader("Model")
    r = st.number_input("Risk-free rate r", value=DEFAULT_R, step=0.005, format="%.4f",
                        help="Constant r. For historical dates set a period-appropriate "
                             "value (e.g. ~0.005 for 2020). Per-date rates are a v2 item.")
    q = st.number_input("Dividend yield q (live mode only)", value=0.0, step=0.0025, format="%.4f",
                        help="Continuous dividend yield. Ignored in historical mode, where "
                             "the parity-implied forward already carries dividends.")
    st.subheader("Filters")
    m_lo, m_hi = st.slider("Moneyness range", 0.5, 1.5, (0.7, 1.3), 0.05)
    t_days = st.slider("Time to expiry (days)", 1, 730, (7, 365))
    st.subheader("Layout")
    n_panels = st.radio("Panels (for comparison)", [1, 2], horizontal=True)

t_range = (t_days[0] / 365, t_days[1] / 365)


# ---------- phase 1: per-panel controls + computation ----------

def panel_controls(i):
    """Render one panel's control box, run the pipeline, return everything the
    chart row needs. Never renders the chart itself - alignment depends on it."""
    st.markdown(f"#### Panel {i + 1}")
    source = st.radio("Data source", ["Live (yfinance)", "Historical (DoltHub)"],
                      key=f"src{i}", horizontal=True)
    symbol = st.text_input("Ticker", "AAPL", key=f"sym{i}").strip().upper()
    mode = st.selectbox("Surface mode", ["stitched OTM", "calls", "puts"], key=f"mode{i}",
                        help="OTM default: out-of-the-money options carry minimal "
                             "American early-exercise premium, so BS fits them best.")
    if not symbol:
        return None

    try:
        anchor_log = ""
        if source.startswith("Live"):
            use_last = st.checkbox(
                "Fallback to lastPrice when bid/ask unusable", key=f"fb{i}",
                help="Rows priced from a (possibly stale) last trade are tagged "
                     "price_source='last'; counts appear in the logs.")
            S, calls_df, puts_df = load_live(symbol)
            st.caption(f"Spot: {S:.2f} (live)")
            title = f"{symbol} {mode} (live)"
        else:
            use_last = False  # historical data has bid/ask only - no lastPrice exists
            c1, c2 = st.columns(2)
            start = c1.date_input("From", date.today() - timedelta(days=30),
                                  min_value=date(2019, 2, 1), key=f"d0{i}")
            end = c2.date_input("To", date.today(), key=f"d1{i}")
            hist = load_hist(symbol, start.isoformat(), end.isoformat())

            # slider over dates that actually exist in the data - never a calendar range
            dates = sorted(hist["date"].unique())
            snap_date = st.select_slider("Snapshot date", options=dates, value=dates[-1],
                                         key=f"snap{i}")
            snap = hist[hist["date"] == snap_date]
            S_close = float(snap["spot"].iloc[0])

            # anchor on the parity-implied forward: immune to spot/quote timing
            # desyncs, dividends already in F -> q must be 0 here
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                snap = anchor_to_forward(snap, r)
            anchor_log = buf.getvalue()
            S = float(snap.sort_values("T")["spot"].iloc[0])  # nearest-expiry implied spot
            st.caption(f"Close on {snap_date}: {S_close:.2f} | parity-implied spot: {S:.2f}"
                       + ("" if abs(S - S_close) < 0.005 * S_close else " (desync corrected)"))
            calls_df = snap[snap["option_type"] == "call"].copy()
            puts_df = snap[snap["option_type"] == "put"].copy()
            title = f"{symbol} {mode} @ {snap_date}"

        q_eff = 0.0 if source.startswith("Historical") else q
        surface, log = compute_surface(calls_df, puts_df, S, r, q_eff, mode,
                                       use_last, (m_lo, m_hi), t_range)
        return dict(surface=surface, S=S, title=title, log=anchor_log + log, error=None)

    except Exception as e:
        return dict(surface=None, S=None, title=symbol, log="", error=str(e))


ctrl_cols = st.columns(n_panels)
results = []
for i, col in enumerate(ctrl_cols):
    with col, st.container(border=True):
        results.append(panel_controls(i))


# ---------- shared color scale: identical cmin/cmax everywhere, one bar ----------

iv_values = pd.concat(
    [res["surface"]["IV"].dropna() for res in results
     if res and res["error"] is None and res["surface"] is not None],
    ignore_index=True,
) if any(res and res["error"] is None for res in results) else pd.Series(dtype=float)
iv_values = iv_values[iv_values.between(0.01, 5)]
zmin, zmax = (float(iv_values.min()), float(iv_values.max())) if not iv_values.empty else (None, None)

# the single colorbar goes under the LAST panel that has a surface
surface_panels = [i for i, res in enumerate(results)
                  if res and res["error"] is None and res["surface"] is not None]
colorbar_panel = surface_panels[-1] if surface_panels else None


# ---------- phase 2: chart row (all charts start at the same height) ----------

chart_cols = st.columns(n_panels)
for i, (col, res) in enumerate(zip(chart_cols, results)):
    with col:
        if res is None:
            continue
        if res["error"] is not None:
            st.error(f"{res['title']}: {res['error']}")
            continue

        fig = visualize(res["surface"], S=res["S"], title=res["title"])
        if zmin is not None:
            fig.update_traces(
                selector=dict(type="surface"),
                cmin=zmin, cmax=zmax,
                showscale=(i == colorbar_panel),
                colorbar=dict(orientation="h", y=-0.12, x=0.5, xanchor="center",
                              thickness=12, len=0.7, title="IV"),
            )
        st.plotly_chart(fig, use_container_width=True, key=f"fig{i}")

        if "price_source" in res["surface"].columns:
            n_last = int((res["surface"]["price_source"] == "last").sum())
            if n_last:
                age = res["surface"].loc[res["surface"]["price_source"] == "last",
                                         "last_trade_age_days"]
                st.warning(f"{n_last}/{len(res['surface'])} points priced from lastPrice "
                           f"(median last trade {age.median():.1f} days old)")

        with st.expander("Console logs"):
            st.code(res["log"] or "(empty)")