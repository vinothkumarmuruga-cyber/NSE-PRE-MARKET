"""
NSE pre-market gainers/losers scanner -- Streamlit Cloud app.

IMPORTANT: this file must be a plain .py file with actual Python source
in it (like this one), not a Jupyter .ipynb renamed to app.py. If you
paste a notebook's raw JSON into app.py, Python parses fields like
"execution_count": null as a dict literal (that part is syntactically
valid Python) but crashes at runtime with `NameError: name 'null' is
not defined`, because JSON's null/true/false aren't Python's
None/True/False. That's what produced the error you saw.

Deploy this file as-is at the path Streamlit points to (e.g.
src/nse-pre-market/app.py in your repo).
"""

import time
from datetime import date, timedelta
from urllib.parse import quote

import pandas as pd
import requests
import streamlit as st
from requests.adapters import HTTPAdapter, Retry

UPSTOX_INSTRUMENT_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"

# Shared session for every Upstox call: pools TCP connections and retries
# transient failures (429/500/502/503/504) automatically.
_upstox_session = requests.Session()
_upstox_session.mount(
    "https://",
    HTTPAdapter(max_retries=Retry(
        total=3, backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )),
)


# ---------------------------------------------------------------------
# Instruments (equities + options)
# ---------------------------------------------------------------------
def normalize_expiry(series):
    numeric = pd.to_numeric(series, errors="coerce")

    if numeric.notna().any():
        return pd.to_datetime(numeric, unit="ms", errors="coerce").dt.date

    return pd.to_datetime(series, errors="coerce").dt.date


@st.cache_data(ttl=3600, show_spinner="Loading instrument list...")
def load_instruments():
    instruments = pd.read_json(UPSTOX_INSTRUMENT_URL, compression="gzip")
    instruments["expiry_date"] = normalize_expiry(instruments["expiry"])

    equities = instruments[
        (instruments["segment"] == "NSE_EQ") &
        (instruments["instrument_type"] == "EQ")
    ].copy()

    options = instruments[
        (instruments["segment"] == "NSE_FO") &
        (instruments["instrument_type"].isin(["CE", "PE"])) &
        (instruments["underlying_type"] == "EQUITY")
    ].copy()

    today = date.today()
    upcoming = options[options["expiry_date"] >= today]
    if upcoming.empty:
        raise RuntimeError(
            "No upcoming options expiry found in the instrument file -- "
            "check that Upstox's NSE.json.gz format hasn't changed."
        )

    nearest_expiry = upcoming["expiry_date"].min()
    options = options[options["expiry_date"] == nearest_expiry].copy()

    return equities, options, nearest_expiry


def nearest_strike(options, symbol, option_type, price):
    chain = options[
        (options["underlying_symbol"] == symbol) &
        (options["instrument_type"] == option_type)
    ]

    if chain.empty or pd.isna(price):
        return None

    diff = (chain["strike_price"] - price).abs()
    nearest = chain.loc[diff.idxmin()]

    return int(nearest["strike_price"])


def option_instrument_key(options, symbol, option_type, strike):
    if strike is None or pd.isna(strike):
        return None

    match = options[
        (options["underlying_symbol"] == symbol) &
        (options["instrument_type"] == option_type) &
        (options["strike_price"] == strike)
    ]

    if match.empty:
        return None

    return match.iloc[0]["instrument_key"]


# ---------------------------------------------------------------------
# NSE pre-open data
# ---------------------------------------------------------------------
def nse_session():
    s = requests.Session()

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/market-data/pre-open-market-cm-and-emerge-market"
    }

    s.get("https://www.nseindia.com", headers=headers, timeout=10)
    return s, headers


def fetch_nse_preopen_fo():
    try:
        s, headers = nse_session()
        url = "https://www.nseindia.com/api/market-data-pre-open?key=FO"
        response = s.get(url, headers=headers, timeout=10)
    except requests.RequestException as e:
        st.warning(f"NSE request failed: {e}")
        return pd.DataFrame()

    if response.status_code != 200:
        st.warning(f"NSE Error: {response.status_code}")
        return pd.DataFrame()

    raw = response.json()
    rows = []

    for item in raw.get("data", []):
        m = item.get("metadata", {})

        rows.append({
            "Symbol": m.get("symbol"),
            "Prev Close": m.get("previousClose"),
            "IEP": m.get("iep"),
            "Change": m.get("change"),
            "% Change": m.get("pChange"),
            "Final": m.get("finalPrice"),
            "Final Quantity": m.get("finalQuantity"),
        })

    df = pd.DataFrame(rows)

    numeric_cols = ["Prev Close", "IEP", "Change", "% Change", "Final", "Final Quantity"]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["Symbol", "IEP", "% Change"])

    return df


# ---------------------------------------------------------------------
# Historical candles (used for prev D/W/M levels + CE/PE prev close)
# ---------------------------------------------------------------------
def fetch_upstox_history(instrument_key, days_back=45, retries=2):
    to_date = date.today() - timedelta(days=1)
    from_date = to_date - timedelta(days=days_back)
    encoded_key = quote(instrument_key, safe="")
    url = f"https://api.upstox.com/v3/historical-candle/{encoded_key}/days/1/{to_date}/{from_date}"

    for attempt in range(retries + 1):
        try:
            response = _upstox_session.get(url, headers={"Accept": "application/json"}, timeout=10)
        except requests.RequestException:
            if attempt == retries:
                return pd.DataFrame()
            time.sleep(0.5 * (attempt + 1))
            continue

        if response.status_code != 200:
            return pd.DataFrame()

        candles = response.json().get("data", {}).get("candles", [])
        if not candles:
            return pd.DataFrame()

        df = pd.DataFrame(
            candles,
            columns=["datetime", "open", "high", "low", "close", "volume", "oi"]
        )
        df["datetime"] = pd.to_datetime(df["datetime"])
        return df.sort_values("datetime")

    return pd.DataFrame()


def get_previous_levels(equity_key):
    hist = fetch_upstox_history(equity_key)

    if hist.empty:
        return None

    prev_day = hist.iloc[-1]
    prev_week = hist.tail(5)
    prev_month = hist.tail(20)

    return {
        "Pre Day High": prev_day["high"],
        "Pre Week High": prev_week["high"].max(),
        "Pre Month High": prev_month["high"].max(),
        "Pre Day Low": prev_day["low"],
        "Pre Week Low": prev_week["low"].min(),
        "Pre Month Low": prev_month["low"].min(),
    }


def get_prev_close(instrument_key):
    if instrument_key is None:
        return None

    hist = fetch_upstox_history(instrument_key)

    if hist.empty:
        return None

    return hist.iloc[-1]["close"]


# ---------------------------------------------------------------------
# Top 5 gainers / losers with CE / PE strikes
# ---------------------------------------------------------------------
def get_top5_premarket_with_strikes(options):
    preopen = fetch_nse_preopen_fo()

    if preopen.empty:
        return pd.DataFrame(), pd.DataFrame()

    rows = []

    for _, row in preopen.iterrows():
        symbol = row["Symbol"]
        pre_open_price = row["IEP"]

        ce_strike = nearest_strike(options, symbol, "CE", pre_open_price)
        pe_strike = nearest_strike(options, symbol, "PE", pre_open_price)

        rows.append({
            "Symbol": symbol,
            "Pre Open": pre_open_price,
            "Prev Close": row["Prev Close"],
            "% Change": row["% Change"],
            "CE Strike": ce_strike,
            "PE Strike": pe_strike
        })

    final = pd.DataFrame(rows)

    for col in ["Pre Open", "Prev Close", "% Change"]:
        final[col] = pd.to_numeric(final[col], errors="coerce").round(2)

    gainers = (
        final.sort_values("% Change", ascending=False)
        .head(5)
        .reset_index(drop=True)
    )

    losers = (
        final.sort_values("% Change", ascending=True)
        .head(5)
        .reset_index(drop=True)
    )

    return gainers, losers


# ---------------------------------------------------------------------
# Add prev D/W/M levels + CE/PE prev close + straddle breakeven levels
# ---------------------------------------------------------------------
def add_levels_and_bep(df, equities, options, side, progress=None):
    rows = []
    total = len(df)

    for i, (_, row) in enumerate(df.iterrows()):
        if progress is not None:
            progress.progress((i + 1) / max(total, 1), text=f"Fetching {row['Symbol']}...")

        symbol = row["Symbol"]
        pre_open = row["Pre Open"]

        match = equities[equities["trading_symbol"] == symbol]
        if match.empty:
            continue

        equity_key = match.iloc[0]["instrument_key"]
        levels = get_previous_levels(equity_key)
        if levels is None:
            continue

        ce_key = option_instrument_key(options, symbol, "CE", row["CE Strike"])
        pe_key = option_instrument_key(options, symbol, "PE", row["PE Strike"])

        pre_close_ce = get_prev_close(ce_key)
        pre_close_pe = get_prev_close(pe_key)

        # NOTE on breakeven: (CE + PE) / 2 is an average premium, not a real
        # breakeven price. A long straddle at a strike breaks even at two
        # prices: strike - total_premium and strike + total_premium.
        avg_premium = None
        bep_upper = None
        bep_lower = None
        if pre_close_ce is not None and pre_close_pe is not None:
            total_premium = pre_close_ce + pre_close_pe
            avg_premium = total_premium / 2
            strike = row["CE Strike"] if row["CE Strike"] == row["PE Strike"] else None
            if strike is not None:
                bep_upper = strike + total_premium
                bep_lower = strike - total_premium

        new_row = row.to_dict()

        if side == "gainer":
            new_row["Pre Day High"] = levels["Pre Day High"]
            new_row["Pre Week High"] = levels["Pre Week High"]
            new_row["Pre Month High"] = levels["Pre Month High"]
            new_row["Day High Status"] = "abv" if pre_open > levels["Pre Day High"] else "--"
            new_row["Week High Status"] = "abv" if pre_open > levels["Pre Week High"] else "--"
            new_row["Month High Status"] = "abv" if pre_open > levels["Pre Month High"] else "--"

        if side == "loser":
            new_row["Pre Day Low"] = levels["Pre Day Low"]
            new_row["Pre Week Low"] = levels["Pre Week Low"]
            new_row["Pre Month Low"] = levels["Pre Month Low"]
            new_row["Day Low Status"] = "blw" if pre_open < levels["Pre Day Low"] else "--"
            new_row["Week Low Status"] = "blw" if pre_open < levels["Pre Week Low"] else "--"
            new_row["Month Low Status"] = "blw" if pre_open < levels["Pre Month Low"] else "--"

        new_row["Pre Close CE"] = pre_close_ce
        new_row["Pre Close PE"] = pre_close_pe
        new_row["BEP"] = avg_premium
        new_row["Straddle BEP Upper"] = bep_upper
        new_row["Straddle BEP Lower"] = bep_lower

        rows.append(new_row)

    result = pd.DataFrame(rows)

    number_cols = [
        "Pre Open", "Prev Close", "% Change",
        "Pre Day High", "Pre Week High", "Pre Month High",
        "Pre Day Low", "Pre Week Low", "Pre Month Low",
        "Pre Close CE", "Pre Close PE", "BEP",
        "Straddle BEP Upper", "Straddle BEP Lower",
    ]
    for col in number_cols:
        if col in result.columns:
            result[col] = pd.to_numeric(result[col], errors="coerce").round(2)

    return result


@st.cache_data(ttl=120, show_spinner=False)
def build_tables():
    equities, options, opt_expiry = load_instruments()
    top5_gainers, top5_losers = get_top5_premarket_with_strikes(options)

    gainers_final = add_levels_and_bep(top5_gainers, equities, options, side="gainer")
    losers_final = add_levels_and_bep(top5_losers, equities, options, side="loser")

    return gainers_final, losers_final, opt_expiry


# ---------------------------------------------------------------------
# Streamlit UI
# ---------------------------------------------------------------------
st.set_page_config(page_title="NSE Pre-Market Scanner", layout="wide")
st.title("NSE Pre-Market Gainers / Losers")

if st.button("Refresh"):
    build_tables.clear()

try:
    gainers_final, losers_final, opt_expiry = build_tables()
except Exception as e:
    st.error(f"Failed to build pre-market tables: {e}")
    st.stop()

st.caption(f"Option expiry used: {opt_expiry}")

st.subheader("Top 5 Gainers")
if gainers_final.empty:
    st.info("No gainers data available right now (pre-open session may be closed).")
else:
    st.dataframe(gainers_final, use_container_width=True)

st.subheader("Top 5 Losers")
if losers_final.empty:
    st.info("No losers data available right now (pre-open session may be closed).")
else:
    st.dataframe(losers_final, use_container_width=True)
