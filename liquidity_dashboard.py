# liquidity_dashboard.py  (re-base to START of window)
# ---------------------------------------------------------
from io import StringIO
import datetime as dt
import pandas as pd
import requests
import streamlit as st

# ---------------------------------------------------------
# CONFIG
# ---------------------------------------------------------
st.set_page_config(page_title="USD Liquidity + BTC/ETH Dashboard", layout="wide")

FRED_SERIES = {
    "TGA (WTREGEN)": "WTREGEN",
    "Fed Balance Sheet (WALCL)": "WALCL",
    "SOMA Holdings (WSHOMCB)": "WSHOMCB",
    "Bank Reserves (WRESBAL)": "WRESBAL",
    "Reverse Repo (ON RRP)": "RRPONTSYD",
}

# ---------------------------------------------------------
# FRED LOADER
# ---------------------------------------------------------
@st.cache_data(ttl=3600, show_spinner="Fetching FRED data…")
def load_fred_series(series_id: str) -> pd.DataFrame:
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    date_col = "DATE" if "DATE" in df.columns else df.columns[0]
    value_col = series_id if series_id in df.columns else df.columns[1]
    df = df.rename(columns={date_col: "date", value_col: "value"})
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.dropna(subset=["date", "value"])[["date", "value"]]

@st.cache_data(ttl=3600)
def load_all_fred(start_date: dt.date) -> pd.DataFrame:
    combined = None
    for label, sid in FRED_SERIES.items():
        df = load_fred_series(sid)
        df = df[df["date"] >= pd.to_datetime(start_date)].rename(columns={"value": label})
        combined = df if combined is None else pd.merge(combined, df, on="date", how="outer")
    return combined.sort_values("date").dropna()

# ---------------------------------------------------------
# LIQUIDITY INDEX
# ---------------------------------------------------------
def compute_liquidity_scores(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in FRED_SERIES.keys():
        mean, std = out[col].mean(), out[col].std() or 1e-9
        out[f"{col}_z"] = (out[col] - mean) / std
    out["TGA (WTREGEN)_z"] *= -1
    out["Reverse Repo (ON RRP)_z"] *= -1
    z_cols = [c for c in out.columns if c.endswith("_z")]
    out["liquidity_z"] = out[z_cols].sum(axis=1)
    out["liquidity_index"] = out["liquidity_z"].rank(pct=True) * 100
    return out

# ---------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------
with st.sidebar:
    st.header("USD Liquidity + BTC/ETH Dashboard")
    st.markdown("**Option C+ Index** (with RRP)")
    start_date = st.date_input("Start Date", value=dt.date(2015, 1, 1), min_value=dt.date(2002, 1, 1))
    if st.button("Force Refresh"):
        st.cache_data.clear()
        st.rerun()

# ---------------------------------------------------------
# LOAD DATA
# ---------------------------------------------------------
raw = load_all_fred(start_date)
df = compute_liquidity_scores(raw)
latest, prev = df.iloc[-1], df.iloc[-2]

# ---------------------------------------------------------
# TABS
# ---------------------------------------------------------
tabs = st.tabs(["Overview", "Liquidity Score", "Components", "S&P 500", "Bitcoin", "Ethereum", "Raw Data"])

with tabs[0]:  # Overview
    st.title("Global USD Liquidity Dashboard")
    cols = st.columns(6)
    for i, col in enumerate(FRED_SERIES.keys()):
        with cols[i]:
            st.metric(col, f"{latest[col]:,.0f}", f"{latest[col] - prev[col]:+,.0f}")
    with cols[5]:
        st.metric("Liquidity Score (z)", f"{latest['liquidity_z']:.2f}", f"{latest['liquidity_z'] - prev['liquidity_z']:+.2f}")
    st.line_chart(df.set_index("date")["liquidity_z"])

with tabs[1]:  # Liquidity Score
    st.metric("Liquidity Index (0–100)", f"{latest['liquidity_index']:.1f}")
    st.line_chart(df.set_index("date")[["liquidity_z", "liquidity_index"]])

with tabs[2]:  # Components
    for col in FRED_SERIES.keys():
        st.subheader(col)
        st.line_chart(df.set_index("date")[col])

with tabs[3]:  # S&P 500
    st.header("Liquidity vs S&P 500")
    sp = load_fred_series("SP500").rename(columns={"value": "price"})
    overlay = pd.merge(df[["date", "liquidity_index"]], sp, on="date", how="inner")
    if not overlay.empty:
        overlay["liq_rebase"] = overlay["liquidity_index"] / overlay["liquidity_index"].iloc[0]
        overlay["sp_rebase"] = overlay["price"] / overlay["price"].iloc[0]
        st.line_chart(overlay.set_index("date")[["liq_rebase", "sp_rebase"]]
                         .rename(columns={"liq_rebase": "Liquidity", "sp_rebase": "S&P 500"}))

with tabs[4]:  # Bitcoin
    import plotly.graph_objects as go

    st.header("Liquidity Index vs Bitcoin Price")
    btc = load_fred_series("CBBTCUSD").rename(columns={"value": "price"})
    overlay = pd.merge(df[["date", "liquidity_index"]], btc, on="date", how="inner")
    if overlay.empty:
        st.warning("No Bitcoin data in selected range (starts 2014-09)")
    else:
        fig = go.Figure()
        # left axis: liquidity
        fig.add_trace(go.Scatter(
            x=overlay["date"], y=overlay["liquidity_index"],
            name="Liquidity Index", yaxis="y", line=dict(color="#00bfff")))
        # right axis: BTC price
        fig.add_trace(go.Scatter(
            x=overlay["date"], y=overlay["price"],
            name="BTC Price", yaxis="y2", line=dict(color="#f7931a")))
        fig.update_layout(
            xaxis_title="Date",
            yaxis=dict(title="Liquidity Index", side="left"),
            yaxis2=dict(title="BTC USD", side="right", overlaying="y", showgrid=False),
            legend=dict(x=0, y=1.1, orientation="h"))
        st.plotly_chart(fig, use_container_width=True)
        st.metric("Latest BTC Price (FRED)", f"${overlay['price'].iloc[-1]:,.0f}")

with tabs[5]:  # Ethereum
    import plotly.graph_objects as go

    st.header("Liquidity Index vs Ethereum Price")
    eth = load_fred_series("CBETHUSD").rename(columns={"value": "price"})
    overlay = pd.merge(df[["date", "liquidity_index"]], eth, on="date", how="inner")
    if overlay.empty:
        st.warning("No Ethereum data — starts ~2017")
    else:
        fig = go.Figure()
        # left axis: liquidity
        fig.add_trace(go.Scatter(
            x=overlay["date"], y=overlay["liquidity_index"],
            name="Liquidity Index", yaxis="y", line=dict(color="#00bfff")))
        # right axis: ETH price
        fig.add_trace(go.Scatter(
            x=overlay["date"], y=overlay["price"],
            name="ETH Price", yaxis="y2", line=dict(color="#627eea")))
        fig.update_layout(
            xaxis_title="Date",
            yaxis=dict(title="Liquidity Index", side="left"),
            yaxis2=dict(title="ETH USD", side="right", overlaying="y", showgrid=False),
            legend=dict(x=0, y=1.1, orientation="h"))
        st.plotly_chart(fig, use_container_width=True)
        st.metric("Latest ETH Price (FRED)", f"${overlay['price'].iloc[-1]:,.0f}")

with tabs[6]:  # Raw Data
    st.dataframe(df, use_container_width=True)
    st.download_button("Download CSV", df.to_csv(index=False), "liquidity_data.csv", "text/csv")

st.success("Dashboard running crash-free with FRED crypto prices (re-based to start of window)")
