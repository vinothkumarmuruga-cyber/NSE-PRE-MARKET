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
# IST TIME
# ============================================================

IST = ZoneInfo("Asia/Kolkata")


def get_ist_time():
    return datetime.now(IST)


# ============================================================
# UPSTOX ACCESS TOKEN
# ============================================================

try:
    ACCESS_TOKEN = st.secrets["upstox"]["access_token"]

except Exception:
    ACCESS_TOKEN = ""


# ============================================================
# LAST UPDATED
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
        padding-top: 0.5rem !important;
        padding-bottom: 0.3rem !important;
        padding-left: 0.8rem !important;
        padding-right: 0.8rem !important;
        max-width: 100% !important;
    }

    header[data-testid="stHeader"] {
        display: none;
    }

    .main-title {
        font-size: 28px;
        font-weight: 750;
        margin-bottom: 4px;
    }

    .section-title {
        font-size: 20px;
        font-weight: 700;
        margin-top: 8px;
        margin-bottom: 4px;
    }

    div[data-testid="stMetric"] {
        border: 1px solid #dddddd;
        border-radius: 8px;
        padding: 6px 12px;
        background: white;
    }

    div[data-testid="stMetricLabel"] {
        font-size: 12px;
    }

    div[data-testid="stMetricValue"] {
        font-size: 23px;
    }

    .footer-text {
        text-align: center;
        font-size: 12px;
        color: #555555;
        margin-top: 5px;
    }

    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# UPSTOX INSTRUMENT MASTER
# ============================================================

UPSTOX_INSTRUMENT_URL = (
    "https://assets.upstox.com/"
    "market-quote/instruments/exchange/"
    "NSE.json.gz"
)


@st.cache_data(
    ttl=3600,
    show_spinner=False
)
def load_instruments():

    return pd.read_json(
        UPSTOX_INSTRUMENT_URL,
        compression="gzip"
    )


# ============================================================
# NSE SESSION
# ============================================================

def create_nse_session():

    session = requests.Session()

    headers = {

        "User-Agent":
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/151.0.0.0 "
            "Safari/537.36",

        "Accept":
            "application/json,text/plain,*/*",

        "Accept-Language":
            "en-US,en;q=0.9",

        "Referer":
            "https://www.nseindia.com/"
    }

    try:

        session.get(
            "https://www.nseindia.com/",
            headers=headers,
            timeout=10
        )

    except Exception:
        pass

    return session, headers


# ============================================================
# NSE PRE-MARKET
# ============================================================

@st.cache_data(
    ttl=60,
    show_spinner=False
)
def fetch_pre_market():

    session, headers = create_nse_session()

    url = (
        "https://www.nseindia.com/"
        "api/market-data-pre-open?key=FO"
    )

    try:

        response = session.get(
            url,
            headers=headers,
            timeout=15
        )

    except Exception as e:

        return pd.DataFrame(), str(e)

    if response.status_code != 200:

        return (
            pd.DataFrame(),
            f"NSE HTTP {response.status_code}"
        )

    try:

        raw = response.json()

    except Exception:

        return (
            pd.DataFrame(),
            "Invalid NSE response"
        )

    rows = []

    for item in raw.get("data", []):

        metadata = item.get(
            "metadata",
            {}
        )

        symbol = metadata.get("symbol")

        iep = metadata.get("iep")

        previous_close = metadata.get(
            "previousClose"
        )

        pchange = metadata.get(
            "pChange"
        )

        if not symbol:
            continue

        rows.append({

            "Symbol": symbol,

            "Pre Open": iep,

            "Prev Close": previous_close,

            "% Change": pchange
        })

    df = pd.DataFrame(rows)

    if df.empty:
        return df, ""

    for col in [
        "Pre Open",
        "Prev Close",
        "% Change"
    ]:

        df[col] = pd.to_numeric(
            df[col],
            errors="coerce"
        )

    df = df.dropna(
        subset=[
            "Symbol",
            "Pre Open",
            "Prev Close"
        ]
    )

    return df, ""


# ============================================================
# GET EQUITY INSTRUMENT
# ============================================================

def get_equity_instrument(
    instruments,
    symbol
):

    df = instruments[
        (
            instruments["segment"]
            == "NSE_EQ"
        )
        &
        (
            instruments["instrument_type"]
            == "EQ"
        )
        &
        (
            instruments["trading_symbol"]
            == symbol
        )
    ]

    if df.empty:
        return None

    return df.iloc[0]


# ============================================================
# GET NEAREST STOCK OPTION EXPIRY
# ============================================================

def get_stock_expiry(
    instruments,
    symbol
):

    today = date.today()

    options = instruments[
        (
            instruments["segment"]
            == "NSE_FO"
        )
        &
        (
            instruments["underlying_symbol"]
            == symbol
        )
        &
        (
            instruments["instrument_type"]
            .isin(["CE", "PE"])
        )
    ].copy()

    if options.empty:
        return None

    options["expiry"] = pd.to_datetime(
        options["expiry"],
        errors="coerce"
    ).dt.date

    options = options[
        options["expiry"] >= today
    ]

    if options.empty:
        return None

    return options["expiry"].min()


# ============================================================
# UPSTOX OPTION CHAIN
# ============================================================

@st.cache_data(
    ttl=30,
    show_spinner=False
)
def get_option_chain(
    access_token,
    underlying_key,
    expiry
):

    if not access_token:
        return pd.DataFrame()

    if not underlying_key:
        return pd.DataFrame()

    if not expiry:
        return pd.DataFrame()

    url = (
        "https://api.upstox.com/v2/"
        "option/chain"
    )

    headers = {

        "Accept":
            "application/json",

        "Authorization":
            f"Bearer {access_token}"
    }

    params = {

        "instrument_key":
            underlying_key,

        "expiry_date":
            expiry.strftime("%Y-%m-%d")
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=15
        )

    except Exception:

        return pd.DataFrame()

    if response.status_code != 200:
        return pd.DataFrame()

    try:

        result = response.json()

    except Exception:

        return pd.DataFrame()

    if result.get("status") != "success":
        return pd.DataFrame()

    data = result.get(
        "data",
        []
    )

    rows = []

    for item in data:

        strike = item.get(
            "strike_price"
        )

        spot = item.get(
            "underlying_spot_price"
        )

        pcr = item.get(
            "pcr"
        )

        # ====================================================
        # CE
        # ====================================================

        call = item.get(
            "call_options",
            {}
        )

        call_market = call.get(
            "market_data",
            {}
        )

        call_greeks = call.get(
            "option_greeks",
            {}
        )

        # ====================================================
        # PE
        # ====================================================

        put = item.get(
            "put_options",
            {}
        )

        put_market = put.get(
            "market_data",
            {}
        )

        put_greeks = put.get(
            "option_greeks",
            {}
        )

        rows.append({

            "Strike": strike,

            # -------------------------------
            # CE
            # -------------------------------

            "CE LTP":
                call_market.get("ltp"),

            "CE Previous Close":
                call_market.get("close_price"),

            "CE OI":
                call_market.get("oi"),

            "CE Previous OI":
                call_market.get("prev_oi"),

            "CE IV":
                call_greeks.get("iv"),

            "CE Delta":
                call_greeks.get("delta"),

            "CE Gamma":
                call_greeks.get("gamma"),

            "CE Theta":
                call_greeks.get("theta"),

            "CE Vega":
                call_greeks.get("vega"),

            # -------------------------------
            # PE
            # -------------------------------

            "PE LTP":
                put_market.get("ltp"),

            "PE Previous Close":
                put_market.get("close_price"),

            "PE OI":
                put_market.get("oi"),

            "PE Previous OI":
                put_market.get("prev_oi"),

            "PE IV":
                put_greeks.get("iv"),

            "PE Delta":
                put_greeks.get("delta"),

            "PE Gamma":
                put_greeks.get("gamma"),

            "PE Theta":
                put_greeks.get("theta"),

            "PE Vega":
                put_greeks.get("vega"),

            # -------------------------------
            # OTHER
            # -------------------------------

            "PCR":
                pcr,

            "Spot":
                spot
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    df = df.sort_values(
        "Strike"
    ).reset_index(drop=True)

    return df


# ============================================================
# FIND NEAREST STRIKE
# ============================================================

def find_nearest_strike(
    option_chain,
    price
):

    if option_chain.empty:
        return None

    if price is None:
        return None

    try:
        price = float(price)
    except Exception:
        return None

    temp = option_chain.copy()

    temp["distance"] = (
        temp["Strike"] - price
    ).abs()

    return temp.sort_values(
        "distance"
    ).iloc[0]["Strike"]


# ============================================================
# GET OPTION DATA FOR STRIKE
# ============================================================

def get_strike_option_data(
    option_chain,
    strike
):

    empty_result = {

        "CE": None,
        "CE_IV": None,

        "PE": None,
        "PE_IV": None,

        "BEP": None
    }

    if option_chain.empty:
        return empty_result

    if strike is None:
        return empty_result

    row = option_chain[
        option_chain["Strike"] == strike
    ]

    if row.empty:
        return empty_result

    row = row.iloc[0]

    ce_close = row.get(
        "CE Previous Close"
    )

    pe_close = row.get(
        "PE Previous Close"
    )

    ce_iv = row.get(
        "CE IV"
    )

    pe_iv = row.get(
        "PE IV"
    )

    bep = None

    if (
        pd.notna(ce_close)
        and
        pd.notna(pe_close)
    ):

        bep = (
            float(ce_close)
            +
            float(pe_close)
        ) / 2

    return {

        "CE": ce_close,

        "CE_IV": ce_iv,

        "PE": pe_close,

        "PE_IV": pe_iv,

        "BEP": bep
    }


# ============================================================
# HISTORICAL DATA
# ============================================================

@st.cache_data(
    ttl=1800,
    show_spinner=False
)
def get_equity_history(
    instrument_key
):

    if not instrument_key:
        return pd.DataFrame()

    to_date = (
        date.today()
        - timedelta(days=1)
    )

    from_date = (
        to_date
        - timedelta(days=60)
    )

    encoded_key = quote(
        instrument_key,
        safe=""
    )

    url = (
        "https://api.upstox.com/v3/"
        "historical-candle/"
        f"{encoded_key}/days/1/"
        f"{to_date}/"
        f"{from_date}"
    )

    headers = {

        "Accept":
            "application/json",

        "Authorization":
            f"Bearer {ACCESS_TOKEN}"
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=15
        )

    except Exception:

        return pd.DataFrame()

    if response.status_code != 200:
        return pd.DataFrame()

    try:

        candles = (
            response.json()
            .get("data", {})
            .get("candles", [])
        )

    except Exception:

        return pd.DataFrame()

    if not candles:
        return pd.DataFrame()

    df = pd.DataFrame(
        candles,
        columns=[
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "oi"
        ]
    )

    df["datetime"] = pd.to_datetime(
        df["datetime"]
    )

    df = df.sort_values(
        "datetime"
    )

    return df


# ============================================================
# PREVIOUS DAY / WEEK / MONTH LEVELS
# ============================================================

def get_previous_levels(
    instrument_key
):

    history = get_equity_history(
        instrument_key
    )

    if history.empty:

        return {

            "Pre Day High": None,
            "Pre Week High": None,
            "Pre Month High": None,

            "Pre Day Low": None,
            "Pre Week Low": None,
            "Pre Month Low": None
        }

    previous_day = history.iloc[-1]

    week_data = history.tail(5)

    month_data = history.tail(20)

    return {

        "Pre Day High":
            previous_day["high"],

        "Pre Week High":
            week_data["high"].max(),

        "Pre Month High":
            month_data["high"].max(),

        "Pre Day Low":
            previous_day["low"],

        "Pre Week Low":
            week_data["low"].min(),

        "Pre Month Low":
            month_data["low"].min()
    }


# ============================================================
# BUILD TOP 5
# ============================================================

def build_top5(
    premarket,
    instruments,
    direction
):

    if premarket.empty:
        return pd.DataFrame()

    # ========================================================
    # SELECT TOP 5
    # ========================================================

    if direction == "gainer":

        selected = (
            premarket
            .sort_values(
                "% Change",
                ascending=False
            )
            .head(5)
        )

    else:

        selected = (
            premarket
            .sort_values(
                "% Change",
                ascending=True
            )
            .head(5)
        )

    rows = []

    # ========================================================
    # EACH STOCK
    # ========================================================

    for _, market_row in selected.iterrows():

        symbol = market_row["Symbol"]

        pre_open = market_row["Pre Open"]

        previous_close = market_row["Prev Close"]

        # ====================================================
        # EQUITY
        # ====================================================

        equity = get_equity_instrument(
            instruments,
            symbol
        )

        if equity is None:
            continue

        equity_key = equity[
            "instrument_key"
        ]

        # ====================================================
        # EXPIRY
        # ====================================================

        expiry = get_stock_expiry(
            instruments,
            symbol
        )

        if expiry is None:
            continue

        # ====================================================
        # OPTION CHAIN
        # ====================================================

        option_chain = get_option_chain(
            ACCESS_TOKEN,
            equity_key,
            expiry
        )

        if option_chain.empty:

            open_strike = None

            pre_close_strike = None

            open_strike_data = {

                "CE_IV": None,
                "PE_IV": None
            }

            pre_close_data = {

                "CE": None,
                "PE": None,
                "BEP": None
            }

        else:

            # =================================================
            # OPEN STRIKE
            #
            # NEAREST STRIKE TO PRE-OPEN PRICE
            # =================================================

            open_strike = find_nearest_strike(
                option_chain,
                pre_open
            )

            # =================================================
            # PRE CLOSE STRIKE
            #
            # NEAREST STRIKE TO PREVIOUS CLOSE
            # =================================================

            pre_close_strike = find_nearest_strike(
                option_chain,
                previous_close
            )

            # =================================================
            # OPEN STRIKE DATA
            #
            # CE IV AND PE IV COME FROM OPEN STRIKE
            # =================================================

            open_strike_data = (
                get_strike_option_data(
                    option_chain,
                    open_strike
                )
            )

            # =================================================
            # PRE CLOSE STRIKE DATA
            #
            # CE/PE PREVIOUS CLOSE + BEP
            # =================================================

            pre_close_data = (
                get_strike_option_data(
                    option_chain,
                    pre_close_strike
                )
            )

        # ====================================================
        # HISTORICAL LEVELS
        # ====================================================

        levels = get_previous_levels(
            equity_key
        )

        # ====================================================
        # BASE ROW
        # ====================================================

        new_row = {

            # -----------------------------------------------
            # STOCK
            # -----------------------------------------------

            "Symbol":
                symbol,

            "Pre Open":
                pre_open,

            "Prev Close":
                previous_close,

            "% Change":
                market_row["% Change"],

            # -----------------------------------------------
            # OPEN STRIKE
            # -----------------------------------------------

            "Open Strike":
                open_strike,

            # -----------------------------------------------
            # OPEN STRIKE IV
            # -----------------------------------------------

            "CE IV":
                open_strike_data["CE_IV"],

            "PE IV":
                open_strike_data["PE_IV"],

            # -----------------------------------------------
            # PRE CLOSE STRIKE
            # -----------------------------------------------

            "Pre Close Strike":
                pre_close_strike,

            # -----------------------------------------------
            # PRE CLOSE OPTIONS
            # -----------------------------------------------

            "Pre Close CE":
                pre_close_data["CE"],

            "Pre Close PE":
                pre_close_data["PE"],

            # -----------------------------------------------
            # BEP
            # -----------------------------------------------

            "BEP":
                pre_close_data["BEP"]
        }

        # ====================================================
        # GAINER LEVELS
        # ====================================================

        if direction == "gainer":

            day_high = levels[
                "Pre Day High"
            ]

            week_high = levels[
                "Pre Week High"
            ]

            month_high = levels[
                "Pre Month High"
            ]

            new_row[
                "Pre Day High"
            ] = day_high

            new_row[
                "Pre Week High"
            ] = week_high

            new_row[
                "Pre Month High"
            ] = month_high

            # -----------------------------------------------
            # STATUS
            # -----------------------------------------------

            new_row[
                "Day High Status"
            ] = (

                "abv"

                if (
                    day_high is not None
                    and
                    pre_open > day_high
                )

                else "--"
            )

            new_row[
                "Week High Status"
            ] = (

                "abv"

                if (
                    week_high is not None
                    and
                    pre_open > week_high
                )

                else "--"
            )

            new_row[
                "Month High Status"
            ] = (

                "abv"

                if (
                    month_high is not None
                    and
                    pre_open > month_high
                )

                else "--"
            )

        # ====================================================
        # LOSER LEVELS
        # ====================================================

        else:

            day_low = levels[
                "Pre Day Low"
            ]

            week_low = levels[
                "Pre Week Low"
            ]

            month_low = levels[
                "Pre Month Low"
            ]

            new_row[
                "Pre Day Low"
            ] = day_low

            new_row[
                "Pre Week Low"
            ] = week_low

            new_row[
                "Pre Month Low"
            ] = month_low

            # -----------------------------------------------
            # STATUS
            # -----------------------------------------------

            new_row[
                "Day Low Status"
            ] = (

                "blw"

                if (
                    day_low is not None
                    and
                    pre_open < day_low
                )

                else "--"
            )

            new_row[
                "Week Low Status"
            ] = (

                "blw"

                if (
                    week_low is not None
                    and
                    pre_open < week_low
                )

                else "--"
            )

            new_row[
                "Month Low Status"
            ] = (

                "blw"

                if (
                    month_low is not None
                    and
                    pre_open < month_low
                )

                else "--"
            )

        rows.append(
            new_row
        )

    return pd.DataFrame(rows)


# ============================================================
# FORMAT GAINER TABLE
# ============================================================

def format_gainer_table(df):

    if df.empty:
        return df

    columns = [

        "Symbol",

        "Pre Open",

        "Prev Close",

        "% Change",

        # ================================================
        # OPEN STRIKE + IV
        # ================================================

        "Open Strike",

        "CE IV",

        "PE IV",

        # ================================================
        # PRE CLOSE STRIKE
        # ================================================

        "Pre Close Strike",

        "Pre Close CE",

        "Pre Close PE",

        "BEP",

        # ================================================
        # LEVELS
        # ================================================

        "Pre Day High",

        "Pre Week High",

        "Pre Month High",

        "Day High Status",

        "Week High Status",

        "Month High Status"
    ]

    columns = [
        c for c in columns
        if c in df.columns
    ]

    return df[columns].copy()


# ============================================================
# FORMAT LOSER TABLE
# ============================================================

def format_loser_table(df):

    if df.empty:
        return df

    columns = [

        "Symbol",

        "Pre Open",

        "Prev Close",

        "% Change",

        # ================================================
        # OPEN STRIKE + IV
        # ================================================

        "Open Strike",

        "CE IV",

        "PE IV",

        # ================================================
        # PRE CLOSE STRIKE
        # ================================================

        "Pre Close Strike",

        "Pre Close CE",

        "Pre Close PE",

        "BEP",

        # ================================================
        # LEVELS
        # ================================================

        "Pre Day Low",

        "Pre Week Low",

        "Pre Month Low",

        "Day Low Status",

        "Week Low Status",

        "Month Low Status"
    ]

    columns = [
        c for c in columns
        if c in df.columns
    ]

    return df[columns].copy()


# ============================================================
# MAIN HEADER
# ============================================================

st.markdown(
    """
    <div class="main-title">
        📊 NSE PRE-MARKET DASHBOARD
    </div>
    """,
    unsafe_allow_html=True
)


# ============================================================
# REFRESH BUTTON
# ============================================================

left_space, refresh_col = st.columns(
    [8, 2]
)

with refresh_col:

    if st.button(
        "🔄 Manual Refresh",
        use_container_width=True
    ):

        st.session_state.last_updated = (
            get_ist_time()
        )

        st.cache_data.clear()

        st.rerun()


# ============================================================
# TOKEN CHECK
# ============================================================

if not ACCESS_TOKEN:

    st.error(
        """
        Upstox access token is missing.

        Create:

        `.streamlit/secrets.toml`

        and add:

        [upstox]

        access_token = "YOUR_UPSTOX_ACCESS_TOKEN"
        """
    )

    st.stop()


# ============================================================
# LOAD DATA
# ============================================================

with st.spinner(
    "Loading NSE pre-market and Upstox option data..."
):

    try:

        instruments = load_instruments()

        premarket, nse_error = (
            fetch_pre_market()
        )

        if premarket.empty:

            st.error(
                "Unable to load NSE pre-market data. "
                + nse_error
            )

            st.stop()

        # ====================================================
        # TOP 5 GAINERS
        # ====================================================

        gainers = build_top5(
            premarket,
            instruments,
            "gainer"
        )

        # ====================================================
        # TOP 5 LOSERS
        # ====================================================

        losers = build_top5(
            premarket,
            instruments,
            "loser"
        )

    except Exception as e:

        st.error(
            f"Dashboard error: {e}"
        )

        st.stop()


# ============================================================
# SUMMARY CARDS
# ============================================================

c1, c2, c3, c4 = st.columns(4)


with c1:

    st.metric(
        "TOP 5 GAINERS",
        len(gainers)
    )


with c2:

    st.metric(
        "TOP 5 LOSERS",
        len(losers)
    )


with c3:

    st.metric(
        "PRE-MARKET CLOSE",
        "09:08 AM"
    )


with c4:

    st.metric(
        "LAST UPDATED",
        st.session_state.last_updated.strftime(
            "%I:%M:%S %p"
        )
    )


# ============================================================
# GAINERS TITLE
# ============================================================

st.markdown(
    """
    <div class="section-title">
        🟢 TOP 5 GAINERS
    </div>
    """,
    unsafe_allow_html=True
)


# ============================================================
# GAINERS TABLE
# ============================================================

if gainers.empty:

    st.warning(
        "No gainer data available."
    )

else:

    gainers_display = (
        format_gainer_table(
            gainers
        )
    )

    st.dataframe(

        gainers_display,

        use_container_width=True,

        hide_index=True,

        height=300,

        column_config={

            "Pre Open":
                st.column_config.NumberColumn(
                    "Pre Open",
                    format="%.2f"
                ),

            "Prev Close":
                st.column_config.NumberColumn(
                    "Prev Close",
                    format="%.2f"
                ),

            "% Change":
                st.column_config.NumberColumn(
                    "% Change",
                    format="%.2f"
                ),

            "Open Strike":
                st.column_config.NumberColumn(
                    "Open Strike",
                    format="%.0f"
                ),

            "CE IV":
                st.column_config.NumberColumn(
                    "CE IV",
                    format="%.2f"
                ),

            "PE IV":
                st.column_config.NumberColumn(
                    "PE IV",
                    format="%.2f"
                ),

            "Pre Close Strike":
                st.column_config.NumberColumn(
                    "Pre Close Strike",
                    format="%.0f"
                ),

            "Pre Close CE":
                st.column_config.NumberColumn(
                    "Pre Close CE",
                    format="%.2f"
                ),

            "Pre Close PE":
                st.column_config.NumberColumn(
                    "Pre Close PE",
                    format="%.2f"
                ),

            "BEP":
                st.column_config.NumberColumn(
                    "BEP",
                    format="%.2f"
                ),

            "Pre Day High":
                st.column_config.NumberColumn(
                    "Pre Day High",
                    format="%.2f"
                ),

            "Pre Week High":
                st.column_config.NumberColumn(
                    "Pre Week High",
                    format="%.2f"
                ),

            "Pre Month High":
                st.column_config.NumberColumn(
                    "Pre Month High",
                    format="%.2f"
                )
        }
    )


# ============================================================
# LOSERS TITLE
# ============================================================

st.markdown(
    """
    <div class="section-title">
        🔴 TOP 5 LOSERS
    </div>
    """,
    unsafe_allow_html=True
)


# ============================================================
# LOSERS TABLE
# ============================================================

if losers.empty:

    st.warning(
        "No loser data available."
    )

else:

    losers_display = (
        format_loser_table(
            losers
        )
    )

    st.dataframe(

        losers_display,

        use_container_width=True,

        hide_index=True,

        height=300,

        column_config={

            "Pre Open":
                st.column_config.NumberColumn(
                    "Pre Open",
                    format="%.2f"
                ),

            "Prev Close":
                st.column_config.NumberColumn(
                    "Prev Close",
                    format="%.2f"
                ),

            "% Change":
                st.column_config.NumberColumn(
                    "% Change",
                    format="%.2f"
                ),

            "Open Strike":
                st.column_config.NumberColumn(
                    "Open Strike",
                    format="%.0f"
                ),

            "CE IV":
                st.column_config.NumberColumn(
                    "CE IV",
                    format="%.2f"
                ),

            "PE IV":
                st.column_config.NumberColumn(
                    "PE IV",
                    format="%.2f"
                ),

            "Pre Close Strike":
                st.column_config.NumberColumn(
                    "Pre Close Strike",
                    format="%.0f"
                ),

            "Pre Close CE":
                st.column_config.NumberColumn(
                    "Pre Close CE",
                    format="%.2f"
                ),

            "Pre Close PE":
                st.column_config.NumberColumn(
                    "Pre Close PE",
                    format="%.2f"
                ),

            "BEP":
                st.column_config.NumberColumn(
                    "BEP",
                    format="%.2f"
                ),

            "Pre Day Low":
                st.column_config.NumberColumn(
                    "Pre Day Low",
                    format="%.2f"
                ),

            "Pre Week Low":
                st.column_config.NumberColumn(
                    "Pre Week Low",
                    format="%.2f"
                ),

            "Pre Month Low":
                st.column_config.NumberColumn(
                    "Pre Month Low",
                    format="%.2f"
                )
        }
    )


# ============================================================
# FOOTER
# ============================================================

last_updated = (
    st.session_state.last_updated
)

st.markdown(
    f"""
    <div class="footer-text">

        NSE Pre-Market:
        <b>09:00 AM - 09:08 AM</b>

        &nbsp;&nbsp; | &nbsp;&nbsp;

        Pre-Market Closing Time:
        <b>09:08 AM</b>

        &nbsp;&nbsp; | &nbsp;&nbsp;

        Last Updated:
        <b>{last_updated.strftime("%I:%M:%S %p")}</b>

        &nbsp;&nbsp; | &nbsp;&nbsp;

        <b>IST</b>

    </div>
    """,
    unsafe_allow_html=True
)
