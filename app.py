import streamlit as st
import requests
import pandas as pd

from datetime import date, timedelta, datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="NSE Pre-Market Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)


# ============================================================
# INDIA TIMEZONE
# ============================================================

IST = ZoneInfo("Asia/Kolkata")


def get_ist_time():
    return datetime.now(IST)


# ============================================================
# UPSTOX INSTRUMENT URL
# ============================================================

UPSTOX_INSTRUMENT_URL = (
    "https://assets.upstox.com/"
    "market-quote/instruments/exchange/NSE.json.gz"
)


# ============================================================
# LAST UPDATED TIME
# ============================================================

if "last_updated" not in st.session_state:

    st.session_state.last_updated = get_ist_time()


# ============================================================
# CSS
# ============================================================

st.markdown(
    """
    <style>

    .block-container {
        padding-top: 0.8rem !important;
        padding-bottom: 0.5rem !important;
        padding-left: 1.0rem !important;
        padding-right: 1.0rem !important;
        max-width: 100% !important;
    }

    header[data-testid="stHeader"] {
        display: none;
    }

    .main-title {
        font-size: 30px;
        font-weight: 750;
        line-height: 1.1;
        margin-bottom: 12px;
    }

    .section-title {
        font-size: 21px;
        font-weight: 700;
        margin-top: 14px;
        margin-bottom: 7px;
    }

    div[data-testid="stMetric"] {
        border: 1px solid #e0e0e0;
        border-radius: 10px;
        padding: 10px 14px;
        min-height: 82px;
        background: white;
    }

    div[data-testid="stMetricLabel"] {
        font-size: 13px;
    }

    div[data-testid="stMetricValue"] {
        font-size: 27px;
    }

    .stButton button {
        height: 40px;
        border-radius: 8px;
        font-weight: 600;
        width: 100%;
    }

    div[data-testid="stDataFrame"] {
        width: 100% !important;
    }

    div[data-testid="stVerticalBlock"] {
        gap: 0.35rem;
    }

    .footer-text {
        text-align: center;
        font-size: 13px;
        color: #555;
        margin-top: 8px;
    }

    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# EXPIRY NORMALIZATION
# ============================================================

def normalize_expiry(series):

    numeric = pd.to_numeric(series, errors="coerce")

    if numeric.notna().any():

        return pd.to_datetime(
            numeric,
            unit="ms",
            errors="coerce"
        ).dt.date

    return pd.to_datetime(
        series,
        errors="coerce"
    ).dt.date


# ============================================================
# LOAD UPSTOX INSTRUMENTS
# ============================================================

@st.cache_data(ttl=3600, show_spinner=False)
def load_instruments():

    instruments = pd.read_json(
        UPSTOX_INSTRUMENT_URL,
        compression="gzip"
    )

    instruments["expiry_date"] = normalize_expiry(instruments["expiry"])

    equities = instruments[
        (instruments["segment"] == "NSE_EQ")
        & (instruments["instrument_type"] == "EQ")
    ].copy()

    options = instruments[
        (instruments["segment"] == "NSE_FO")
        & (instruments["instrument_type"].isin(["CE", "PE"]))
        & (instruments["underlying_type"] == "EQUITY")
    ].copy()

    today = date.today()

    future_expiries = options[options["expiry_date"] >= today]["expiry_date"]

    if future_expiries.empty:
        return equities, options, None

    nearest_expiry = future_expiries.min()

    options = options[options["expiry_date"] == nearest_expiry].copy()

    return equities, options, nearest_expiry


# ============================================================
# FIND NEAREST STRIKE
# ============================================================

def nearest_strike(options, symbol, option_type, price):

    if price is None or pd.isna(price):
        return None

    chain = options[
        (options["underlying_symbol"] == symbol)
        & (options["instrument_type"] == option_type)
    ].copy()

    if chain.empty:
        return None

    chain["difference"] = (chain["strike_price"] - float(price)).abs()

    nearest = chain.sort_values("difference").iloc[0]

    return int(nearest["strike_price"])


# ============================================================
# FIND OPTION INSTRUMENT KEY
# ============================================================

def option_instrument_key(options, symbol, option_type, strike):

    if strike is None:
        return None

    match = options[
        (options["underlying_symbol"] == symbol)
        & (options["instrument_type"] == option_type)
        & (options["strike_price"] == strike)
    ]

    if match.empty:
        return None

    return match.iloc[0]["instrument_key"]


# ============================================================
# NSE SESSION
# ============================================================
#
# NSE blocks requests that don't look like a real browser
# session, AND separately blackholes many cloud/datacenter IP
# ranges (including Streamlit Cloud) regardless of headers.
# Strategy:
#   1. Try direct, with a full realistic browser handshake.
#   2. If that 401/403s, fall back to a public proxy relay
#      (allorigins) so the request originates from a
#      different IP entirely.
# ============================================================

NSE_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def nse_session():

    session = requests.Session()

    base_headers = {
        "User-Agent": NSE_UA,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Upgrade-Insecure-Requests": "1",
    }

    try:
        session.get(
            "https://www.nseindia.com",
            headers={**base_headers, "Sec-Fetch-Site": "none",
                     "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"},
            timeout=10
        )

        session.get(
            "https://www.nseindia.com/market-data/pre-open-market-cm-and-emerge-market",
            headers={**base_headers, "Sec-Fetch-Site": "same-origin",
                     "Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document",
                     "Referer": "https://www.nseindia.com/"},
            timeout=10
        )

    except Exception:
        pass

    api_headers = dict(base_headers)
    api_headers.update({
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nseindia.com/market-data/pre-open-market-cm-and-emerge-market",
        "X-Requested-With": "XMLHttpRequest",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    })

    return session, api_headers


def fetch_nse_direct(url):
    session, headers = nse_session()
    try:
        response = session.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None


def fetch_nse_via_proxy(url):
    # allorigins fetches server-side on its own IP, sidestepping
    # NSE's block on Streamlit Cloud's IP range.
    proxy_url = "https://api.allorigins.win/raw?url=" + quote(url, safe="")
    try:
        response = requests.get(proxy_url, timeout=20)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None


# ============================================================
# NSE PRE-OPEN DATA
# ============================================================

@st.cache_data(ttl=60, show_spinner=False)
def fetch_nse_preopen_fo():

    url = "https://www.nseindia.com/api/market-data-pre-open?key=FO"

    raw = fetch_nse_direct(url)

    source = "direct"

    if raw is None:
        raw = fetch_nse_via_proxy(url)
        source = "proxy"

    if raw is None:
        st.error(
            "NSE Error: both direct and proxy fetch failed. "
            "NSE is blocking/rate-limiting this connection — "
            "try Manual Refresh in a minute."
        )
        return pd.DataFrame()

    if source == "proxy":
        st.caption("⚠️ Fetched via proxy relay (direct NSE connection was blocked).")

    rows = []

    for item in raw.get("data", []):

        metadata = item.get("metadata", {})

        rows.append({
            "Symbol": metadata.get("symbol"),
            "Prev Close": metadata.get("previousClose"),
            "IEP": metadata.get("iep"),
            "Change": metadata.get("change"),
            "% Change": metadata.get("pChange"),
            "Final": metadata.get("finalPrice")
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return df

    numeric_columns = ["Prev Close", "IEP", "Change", "% Change", "Final"]

    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=["Symbol", "IEP", "% Change"])

    return df


# ============================================================
# UPSTOX HISTORICAL DATA
# ============================================================

@st.cache_data(ttl=1800, show_spinner=False)
def fetch_upstox_history(instrument_key, days_back=45):

    if not instrument_key:
        return pd.DataFrame()

    to_date = date.today() - timedelta(days=1)
    from_date = to_date - timedelta(days=days_back)

    encoded_key = quote(instrument_key, safe="")

    url = (
        "https://api.upstox.com/v3/historical-candle/"
        f"{encoded_key}/days/1/{to_date}/{from_date}"
    )

    try:
        response = requests.get(
            url,
            headers={"Accept": "application/json"},
            timeout=15
        )
    except Exception:
        return pd.DataFrame()

    if response.status_code != 200:
        return pd.DataFrame()

    try:
        candles = response.json().get("data", {}).get("candles", [])
    except Exception:
        return pd.DataFrame()

    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(
        candles,
        columns=["datetime", "open", "high", "low", "close", "volume", "oi"]
    )

    df["datetime"] = pd.to_datetime(df["datetime"])

    df = df.sort_values("datetime")

    return df


# ============================================================
# PREVIOUS DAY / WEEK / MONTH LEVELS
# ============================================================

def get_previous_levels(equity_key):

    history = fetch_upstox_history(equity_key)

    if history.empty:
        return None

    previous_day = history.iloc[-1]
    previous_week = history.tail(5)
    previous_month = history.tail(20)

    return {
        "Pre Day High": previous_day["high"],
        "Pre Week High": previous_week["high"].max(),
        "Pre Month High": previous_month["high"].max(),
        "Pre Day Low": previous_day["low"],
        "Pre Week Low": previous_week["low"].min(),
        "Pre Month Low": previous_month["low"].min()
    }


# ============================================================
# PREVIOUS OPTION CLOSE
# ============================================================

def get_previous_option_close(instrument_key):

    if instrument_key is None:
        return None

    history = fetch_upstox_history(instrument_key)

    if history.empty:
        return None

    return history.iloc[-1]["close"]


# ============================================================
# CREATE TOP 5
# ============================================================

def get_top5_premarket(options):

    preopen = fetch_nse_preopen_fo()

    if preopen.empty:
        return pd.DataFrame(), pd.DataFrame()

    rows = []

    for _, row in preopen.iterrows():

        symbol = row["Symbol"]
        pre_open_price = row["IEP"]
        previous_close = row["Prev Close"]

        open_strike_ce = nearest_strike(options, symbol, "CE", pre_open_price)
        open_strike = open_strike_ce

        pre_close_strike_ce = nearest_strike(options, symbol, "CE", previous_close)
        pre_close_strike = pre_close_strike_ce

        rows.append({
            "Symbol": symbol,
            "Pre Open": pre_open_price,
            "Prev Close": previous_close,
            "% Change": row["% Change"],
            "Open Strike": open_strike,
            "Pre Close Strike": pre_close_strike
        })

    final = pd.DataFrame(rows)

    if final.empty:
        return pd.DataFrame(), pd.DataFrame()

    numeric_columns = ["Pre Open", "Prev Close", "% Change"]

    for column in numeric_columns:
        final[column] = pd.to_numeric(final[column], errors="coerce")

    gainers = final.sort_values("% Change", ascending=False).head(5).reset_index(drop=True)
    losers = final.sort_values("% Change", ascending=True).head(5).reset_index(drop=True)

    return gainers, losers


# ============================================================
# ADD LEVELS AND OPTION DATA
# ============================================================

def add_levels_and_options(df, equities, options, side):

    rows = []

    for _, row in df.iterrows():

        symbol = row["Symbol"]
        pre_open = row["Pre Open"]

        equity_match = equities[equities["trading_symbol"] == symbol]

        if equity_match.empty:
            continue

        equity_key = equity_match.iloc[0]["instrument_key"]

        levels = get_previous_levels(equity_key)

        if levels is None:
            continue

        open_strike = row["Open Strike"]
        pre_close_strike = row["Pre Close Strike"]

        ce_key = option_instrument_key(options, symbol, "CE", pre_close_strike)
        pe_key = option_instrument_key(options, symbol, "PE", pre_close_strike)

        previous_ce_close = get_previous_option_close(ce_key)
        previous_pe_close = get_previous_option_close(pe_key)

        bep = None

        if previous_ce_close is not None and previous_pe_close is not None:
            bep = (previous_ce_close + previous_pe_close) / 2

        new_row = row.to_dict()

        if side == "gainer":

            new_row["Pre Day High"] = levels["Pre Day High"]
            new_row["Pre Week High"] = levels["Pre Week High"]
            new_row["Pre Month High"] = levels["Pre Month High"]

            new_row["Day High Status"] = "abv" if pre_open > levels["Pre Day High"] else "--"
            new_row["Week High Status"] = "abv" if pre_open > levels["Pre Week High"] else "--"
            new_row["Month High Status"] = "abv" if pre_open > levels["Pre Month High"] else "--"

        else:

            new_row["Pre Day Low"] = levels["Pre Day Low"]
            new_row["Pre Week Low"] = levels["Pre Week Low"]
            new_row["Pre Month Low"] = levels["Pre Month Low"]

            new_row["Day Low Status"] = "blw" if pre_open < levels["Pre Day Low"] else "--"
            new_row["Week Low Status"] = "blw" if pre_open < levels["Pre Week Low"] else "--"
            new_row["Month Low Status"] = "blw" if pre_open < levels["Pre Month Low"] else "--"

        new_row["Pre Close CE"] = previous_ce_close
        new_row["Pre Close PE"] = previous_pe_close
        new_row["BEP"] = bep

        rows.append(new_row)

    result = pd.DataFrame(rows)

    if result.empty:
        return result

    numeric_columns = [
        "Pre Open", "Prev Close", "% Change",
        "Pre Day High", "Pre Week High", "Pre Month High",
        "Pre Day Low", "Pre Week Low", "Pre Month Low",
        "Pre Close CE", "Pre Close PE", "BEP"
    ]

    for column in numeric_columns:
        if column in result.columns:
            result[column] = pd.to_numeric(result[column], errors="coerce").round(2)

    return result


# ============================================================
# FORMAT GAINER TABLE
# ============================================================

def format_gainer_table(df):

    if df.empty:
        return df

    columns = [
        "Symbol", "Pre Open", "Prev Close", "% Change",
        "Open Strike", "Pre Close Strike",
        "Pre Day High", "Pre Week High", "Pre Month High",
        "Day High Status", "Week High Status", "Month High Status",
        "Pre Close CE", "Pre Close PE", "BEP"
    ]

    columns = [c for c in columns if c in df.columns]

    return df[columns].copy()


# ============================================================
# FORMAT LOSER TABLE
# ============================================================

def format_loser_table(df):

    if df.empty:
        return df

    columns = [
        "Symbol", "Pre Open", "Prev Close", "% Change",
        "Open Strike", "Pre Close Strike",
        "Pre Day Low", "Pre Week Low", "Pre Month Low",
        "Day Low Status", "Week Low Status", "Month Low Status",
        "Pre Close CE", "Pre Close PE", "BEP"
    ]

    columns = [c for c in columns if c in df.columns]

    return df[columns].copy()


# ============================================================
# HEADER
# ============================================================

st.markdown(
    '<div class="main-title">📊 NSE PRE-MARKET DASHBOARD</div>',
    unsafe_allow_html=True
)


# ============================================================
# TOP RIGHT MANUAL REFRESH
# ============================================================

left_space, refresh_space = st.columns([8, 2])

with refresh_space:

    if st.button("🔄 Manual Refresh", use_container_width=True):

        st.session_state.last_updated = get_ist_time()

        st.cache_data.clear()

        st.rerun()


# ============================================================
# LOAD DATA
# ============================================================

with st.spinner("Loading NSE pre-market data..."):

    try:

        equities, options, option_expiry = load_instruments()

        if option_expiry is None:
            st.error("No future option expiry found.")
            st.stop()

        top5_gainers, top5_losers = get_top5_premarket(options)

        gainers_final = add_levels_and_options(top5_gainers, equities, options, "gainer")
        losers_final = add_levels_and_options(top5_losers, equities, options, "loser")

    except Exception as e:
        st.error(f"Dashboard error: {e}")
        st.stop()


# ============================================================
# SUMMARY CARDS
# ============================================================

c1, c2, c3, c4 = st.columns(4)

with c1:
    st.metric("TOP 5 GAINERS", len(gainers_final))

with c2:
    st.metric("TOP 5 LOSERS", len(losers_final))

with c3:
    st.metric("OPTION EXPIRY", str(option_expiry))

with c4:
    st.metric("LAST UPDATED", st.session_state.last_updated.strftime("%I:%M:%S %p"))


# ============================================================
# TOP 5 GAINERS
# ============================================================

st.markdown(
    '<div class="section-title">🟢 TOP 5 GAINERS</div>',
    unsafe_allow_html=True
)

if gainers_final.empty:

    st.warning("No gainer data available.")

else:

    gainers_display = format_gainer_table(gainers_final)

    st.dataframe(
        gainers_display,
        use_container_width=True,
        hide_index=True,
        height=285,
        column_config={
            "Symbol": st.column_config.TextColumn("Symbol"),
            "Pre Open": st.column_config.NumberColumn("Pre Open", format="%.2f"),
            "Prev Close": st.column_config.NumberColumn("Prev Close", format="%.2f"),
            "% Change": st.column_config.NumberColumn("% Change", format="%.2f"),
            "Open Strike": st.column_config.NumberColumn("Open Strike", format="%.0f"),
            "Pre Close Strike": st.column_config.NumberColumn("Pre Close Strike", format="%.0f"),
            "Pre Day High": st.column_config.NumberColumn("Pre Day High", format="%.2f"),
            "Pre Week High": st.column_config.NumberColumn("Pre Week High", format="%.2f"),
            "Pre Month High": st.column_config.NumberColumn("Pre Month High", format="%.2f"),
            "Pre Close CE": st.column_config.NumberColumn("Pre Close CE", format="%.2f"),
            "Pre Close PE": st.column_config.NumberColumn("Pre Close PE", format="%.2f"),
            "BEP": st.column_config.NumberColumn("BEP", format="%.2f")
        }
    )


# ============================================================
# TOP 5 LOSERS
# ============================================================

st.markdown(
    '<div class="section-title">🔴 TOP 5 LOSERS</div>',
    unsafe_allow_html=True
)

if losers_final.empty:

    st.warning("No loser data available.")

else:

    losers_display = format_loser_table(losers_final)

    st.dataframe(
        losers_display,
        use_container_width=True,
        hide_index=True,
        height=285,
        column_config={
            "Symbol": st.column_config.TextColumn("Symbol"),
            "Pre Open": st.column_config.NumberColumn("Pre Open", format="%.2f"),
            "Prev Close": st.column_config.NumberColumn("Prev Close", format="%.2f"),
            "% Change": st.column_config.NumberColumn("% Change", format="%.2f"),
            "Open Strike": st.column_config.NumberColumn("Open Strike", format="%.0f"),
            "Pre Close Strike": st.column_config.NumberColumn("Pre Close Strike", format="%.0f"),
            "Pre Day Low": st.column_config.NumberColumn("Pre Day Low", format="%.2f"),
            "Pre Week Low": st.column_config.NumberColumn("Pre Week Low", format="%.2f"),
            "Pre Month Low": st.column_config.NumberColumn("Pre Month Low", format="%.2f"),
            "Pre Close CE": st.column_config.NumberColumn("Pre Close CE", format="%.2f"),
            "Pre Close PE": st.column_config.NumberColumn("Pre Close PE", format="%.2f"),
            "BEP": st.column_config.NumberColumn("BEP", format="%.2f")
        }
    )


# ============================================================
# FOOTER  (FIXED: single-line HTML so Markdown doesn't
# treat the indented content as a code block)
# ============================================================

current_updated = st.session_state.last_updated

footer_html = (
    '<div class="footer-text">'
    'NSE Pre-Market Data &nbsp;&nbsp;|&nbsp;&nbsp; '
    f'Last Updated: <b>{current_updated.strftime("%I:%M:%S %p")}</b> '
    '&nbsp;&nbsp;|&nbsp;&nbsp; Time Zone: <b>IST</b>'
    '</div>'
)

st.markdown(footer_html, unsafe_allow_html=True)
