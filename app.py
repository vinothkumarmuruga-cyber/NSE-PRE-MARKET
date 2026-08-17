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

    /* ======================================================
       FULL WIDTH
       ====================================================== */

    .block-container {
        padding-top: 0.8rem !important;
        padding-bottom: 0.5rem !important;
        padding-left: 1.0rem !important;
        padding-right: 1.0rem !important;
        max-width: 100% !important;
    }


    /* ======================================================
       HIDE STREAMLIT HEADER
       ====================================================== */

    header[data-testid="stHeader"] {
        display: none;
    }


    /* ======================================================
       MAIN TITLE
       ====================================================== */

    .main-title {
        font-size: 30px;
        font-weight: 750;
        line-height: 1.1;
        margin-bottom: 12px;
    }


    /* ======================================================
       SECTION TITLE
       ====================================================== */

    .section-title {
        font-size: 21px;
        font-weight: 700;
        margin-top: 14px;
        margin-bottom: 7px;
    }


    /* ======================================================
       METRIC CARDS
       ====================================================== */

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


    /* ======================================================
       BUTTON
       ====================================================== */

    .stButton button {

        height: 40px;

        border-radius: 8px;

        font-weight: 600;

        width: 100%;
    }


    /* ======================================================
       DATAFRAME
       ====================================================== */

    div[data-testid="stDataFrame"] {

        width: 100% !important;
    }


    /* ======================================================
       REMOVE EXCESS GAP
       ====================================================== */

    div[data-testid="stVerticalBlock"] {

        gap: 0.35rem;
    }


    /* ======================================================
       FOOTER
       ====================================================== */

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

    numeric = pd.to_numeric(
        series,
        errors="coerce"
    )

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

@st.cache_data(
    ttl=3600,
    show_spinner=False
)
def load_instruments():

    instruments = pd.read_json(
        UPSTOX_INSTRUMENT_URL,
        compression="gzip"
    )

    instruments["expiry_date"] = (
        normalize_expiry(
            instruments["expiry"]
        )
    )


    # ========================================================
    # NSE EQUITY
    # ========================================================

    equities = instruments[
        (instruments["segment"] == "NSE_EQ")
        &
        (
            instruments["instrument_type"]
            == "EQ"
        )
    ].copy()


    # ========================================================
    # NSE OPTIONS
    # ========================================================

    options = instruments[
        (instruments["segment"] == "NSE_FO")
        &
        (
            instruments["instrument_type"]
            .isin(["CE", "PE"])
        )
        &
        (
            instruments["underlying_type"]
            == "EQUITY"
        )
    ].copy()


    today = date.today()


    future_expiries = options[
        options["expiry_date"] >= today
    ]["expiry_date"]


    if future_expiries.empty:

        return (
            equities,
            options,
            None
        )


    nearest_expiry = (
        future_expiries.min()
    )


    options = options[
        options["expiry_date"]
        == nearest_expiry
    ].copy()


    return (
        equities,
        options,
        nearest_expiry
    )


# ============================================================
# FIND NEAREST STRIKE
# ============================================================

def nearest_strike(
    options,
    symbol,
    option_type,
    price
):

    if price is None:

        return None


    if pd.isna(price):

        return None


    chain = options[
        (options["underlying_symbol"] == symbol)
        &
        (
            options["instrument_type"]
            == option_type
        )
    ].copy()


    if chain.empty:

        return None


    chain["difference"] = (
        chain["strike_price"]
        - float(price)
    ).abs()


    nearest = (
        chain
        .sort_values(
            "difference"
        )
        .iloc[0]
    )


    return int(
        nearest["strike_price"]
    )


# ============================================================
# FIND OPTION INSTRUMENT KEY
# ============================================================

def option_instrument_key(
    options,
    symbol,
    option_type,
    strike
):

    if strike is None:

        return None


    match = options[
        (options["underlying_symbol"] == symbol)
        &
        (
            options["instrument_type"]
            == option_type
        )
        &
        (
            options["strike_price"]
            == strike
        )
    ]


    if match.empty:

        return None


    return match.iloc[0][
        "instrument_key"
    ]


# ============================================================
# NSE SESSION
# ============================================================

def nse_session():

    session = requests.Session()


    headers = {

        headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
}

    

        "Referer":
            "https://www.nseindia.com/"
    }


    try:

        session.get(
            "https://www.nseindia.com",
            headers=headers,
            timeout=10
        )

    except Exception:

        pass


    return session, headers


# ============================================================
# NSE PRE-OPEN DATA
# ============================================================

def fetch_nse_preopen_fo():

    session, headers = (
        nse_session()
    )


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

        st.error(
            f"NSE connection error: {e}"
        )

        return pd.DataFrame()


    if response.status_code != 200:

        st.error(
            f"NSE Error: HTTP "
            f"{response.status_code}"
        )

        return pd.DataFrame()


    try:

        raw = response.json()

    except Exception:

        st.error(
            "NSE returned invalid JSON."
        )

        return pd.DataFrame()


    rows = []


    for item in raw.get(
        "data",
        []
    ):

        metadata = item.get(
            "metadata",
            {}
        )


        rows.append({

            "Symbol":
                metadata.get(
                    "symbol"
                ),

            "Prev Close":
                metadata.get(
                    "previousClose"
                ),

            "IEP":
                metadata.get(
                    "iep"
                ),

            "Change":
                metadata.get(
                    "change"
                ),

            "% Change":
                metadata.get(
                    "pChange"
                ),

            "Final":
                metadata.get(
                    "finalPrice"
                )

        })


    df = pd.DataFrame(
        rows
    )


    if df.empty:

        return df


    numeric_columns = [

        "Prev Close",
        "IEP",
        "Change",
        "% Change",
        "Final"

    ]


    for column in numeric_columns:

        df[column] = pd.to_numeric(
            df[column],
            errors="coerce"
        )


    df = df.dropna(
        subset=[
            "Symbol",
            "IEP",
            "% Change"
        ]
    )


    return df


# ============================================================
# UPSTOX HISTORICAL DATA
# ============================================================

@st.cache_data(
    ttl=1800,
    show_spinner=False
)
def fetch_upstox_history(
    instrument_key,
    days_back=45
):

    if not instrument_key:

        return pd.DataFrame()


    to_date = (
        date.today()
        - timedelta(days=1)
    )


    from_date = (
        to_date
        - timedelta(days=days_back)
    )


    encoded_key = quote(
        instrument_key,
        safe=""
    )


    url = (
        "https://api.upstox.com/v3/"
        "historical-candle/"
        f"{encoded_key}/days/1/"
        f"{to_date}/{from_date}"
    )


    try:

        response = requests.get(
            url,
            headers={
                "Accept":
                    "application/json"
            },
            timeout=15
        )

    except Exception:

        return pd.DataFrame()


    if response.status_code != 200:

        return pd.DataFrame()


    try:

        candles = (
            response
            .json()
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
    equity_key
):

    history = fetch_upstox_history(
        equity_key
    )


    if history.empty:

        return None


    previous_day = (
        history.iloc[-1]
    )


    previous_week = (
        history.tail(5)
    )


    previous_month = (
        history.tail(20)
    )


    return {

        "Pre Day High":
            previous_day["high"],

        "Pre Week High":
            previous_week["high"].max(),

        "Pre Month High":
            previous_month["high"].max(),

        "Pre Day Low":
            previous_day["low"],

        "Pre Week Low":
            previous_week["low"].min(),

        "Pre Month Low":
            previous_month["low"].min()

    }


# ============================================================
# PREVIOUS OPTION CLOSE
# ============================================================

def get_previous_option_close(
    instrument_key
):

    if instrument_key is None:

        return None


    history = fetch_upstox_history(
        instrument_key
    )


    if history.empty:

        return None


    return history.iloc[-1]["close"]


# ============================================================
# CREATE TOP 5
# ============================================================

def get_top5_premarket(
    options
):

    preopen = (
        fetch_nse_preopen_fo()
    )


    if preopen.empty:

        return (
            pd.DataFrame(),
            pd.DataFrame()
        )


    rows = []


    for _, row in preopen.iterrows():

        symbol = row["Symbol"]

        pre_open_price = row["IEP"]

        previous_close = row[
            "Prev Close"
        ]


        # ====================================================
        # OPEN STRIKE
        #
        # Based on PRE-OPEN price
        # ====================================================

        open_strike_ce = nearest_strike(
            options,
            symbol,
            "CE",
            pre_open_price
        )


        # CE and PE have same strike
        # so use one Open Strike

        open_strike = (
            open_strike_ce
        )


        # ====================================================
        # PRE CLOSE STRIKE
        #
        # Based on PREVIOUS CLOSE
        # ====================================================

        pre_close_strike_ce = (
            nearest_strike(
                options,
                symbol,
                "CE",
                previous_close
            )
        )


        pre_close_strike = (
            pre_close_strike_ce
        )


        rows.append({

            "Symbol":
                symbol,

            "Pre Open":
                pre_open_price,

            "Prev Close":
                previous_close,

            "% Change":
                row["% Change"],

            "Open Strike":
                open_strike,

            "Pre Close Strike":
                pre_close_strike

        })


    final = pd.DataFrame(
        rows
    )


    if final.empty:

        return (
            pd.DataFrame(),
            pd.DataFrame()
        )


    numeric_columns = [

        "Pre Open",
        "Prev Close",
        "% Change"

    ]


    for column in numeric_columns:

        final[column] = pd.to_numeric(
            final[column],
            errors="coerce"
        )


    # ========================================================
    # TOP 5 GAINERS
    # ========================================================

    gainers = (
        final
        .sort_values(
            "% Change",
            ascending=False
        )
        .head(5)
        .reset_index(drop=True)
    )


    # ========================================================
    # TOP 5 LOSERS
    # ========================================================

    losers = (
        final
        .sort_values(
            "% Change",
            ascending=True
        )
        .head(5)
        .reset_index(drop=True)
    )


    return (
        gainers,
        losers
    )


# ============================================================
# ADD LEVELS AND OPTION DATA
# ============================================================

def add_levels_and_options(
    df,
    equities,
    options,
    side
):

    rows = []


    for _, row in df.iterrows():

        symbol = row["Symbol"]

        pre_open = row["Pre Open"]

        previous_close = (
            row["Prev Close"]
        )


        # ====================================================
        # EQUITY INSTRUMENT
        # ====================================================

        equity_match = equities[
            equities["trading_symbol"]
            == symbol
        ]


        if equity_match.empty:

            continue


        equity_key = (
            equity_match
            .iloc[0]["instrument_key"]
        )


        # ====================================================
        # PREVIOUS LEVELS
        # ====================================================

        levels = get_previous_levels(
            equity_key
        )


        if levels is None:

            continue


        # ====================================================
        # IMPORTANT:
        #
        # OPEN STRIKE
        # = based on PRE OPEN
        #
        # PRE CLOSE STRIKE
        # = based on PREVIOUS CLOSE
        # ====================================================

        open_strike = (
            row["Open Strike"]
        )


        pre_close_strike = (
            row["Pre Close Strike"]
        )


        # ====================================================
        # OPTION KEYS
        #
        # IMPORTANT:
        # PREVIOUS OPTION CLOSE
        # uses PRE CLOSE STRIKE
        # ====================================================

        ce_key = option_instrument_key(
            options,
            symbol,
            "CE",
            pre_close_strike
        )


        pe_key = option_instrument_key(
            options,
            symbol,
            "PE",
            pre_close_strike
        )


        # ====================================================
        # PREVIOUS CE CLOSE
        # ====================================================

        previous_ce_close = (
            get_previous_option_close(
                ce_key
            )
        )


        # ====================================================
        # PREVIOUS PE CLOSE
        # ====================================================

        previous_pe_close = (
            get_previous_option_close(
                pe_key
            )
        )


        # ====================================================
        # BEP
        # ====================================================

        bep = None


        if (
            previous_ce_close is not None
            and
            previous_pe_close is not None
        ):

            bep = (
                previous_ce_close
                +
                previous_pe_close
            ) / 2


        new_row = row.to_dict()


        # ====================================================
        # COMMON LEVELS
        # ====================================================

        if side == "gainer":

            new_row[
                "Pre Day High"
            ] = levels[
                "Pre Day High"
            ]


            new_row[
                "Pre Week High"
            ] = levels[
                "Pre Week High"
            ]


            new_row[
                "Pre Month High"
            ] = levels[
                "Pre Month High"
            ]


            # ------------------------------------------------
            # HIGH STATUS
            # ------------------------------------------------

            new_row[
                "Day High Status"
            ] = (

                "abv"

                if pre_open
                > levels["Pre Day High"]

                else "--"
            )


            new_row[
                "Week High Status"
            ] = (

                "abv"

                if pre_open
                > levels["Pre Week High"]

                else "--"
            )


            new_row[
                "Month High Status"
            ] = (

                "abv"

                if pre_open
                > levels["Pre Month High"]

                else "--"
            )


        else:

            new_row[
                "Pre Day Low"
            ] = levels[
                "Pre Day Low"
            ]


            new_row[
                "Pre Week Low"
            ] = levels[
                "Pre Week Low"
            ]


            new_row[
                "Pre Month Low"
            ] = levels[
                "Pre Month Low"
            ]


            # ------------------------------------------------
            # LOW STATUS
            # ------------------------------------------------

            new_row[
                "Day Low Status"
            ] = (

                "blw"

                if pre_open
                < levels["Pre Day Low"]

                else "--"
            )


            new_row[
                "Week Low Status"
            ] = (

                "blw"

                if pre_open
                < levels["Pre Week Low"]

                else "--"
            )


            new_row[
                "Month Low Status"
            ] = (

                "blw"

                if pre_open
                < levels["Pre Month Low"]

                else "--"
            )


        # ====================================================
        # OPTION DATA
        # ====================================================

        new_row[
            "Pre Close CE"
        ] = previous_ce_close


        new_row[
            "Pre Close PE"
        ] = previous_pe_close


        new_row[
            "BEP"
        ] = bep


        rows.append(
            new_row
        )


    result = pd.DataFrame(
        rows
    )


    if result.empty:

        return result


    # ========================================================
    # ROUND NUMBERS
    # ========================================================

    numeric_columns = [

        "Pre Open",
        "Prev Close",
        "% Change",

        "Pre Day High",
        "Pre Week High",
        "Pre Month High",

        "Pre Day Low",
        "Pre Week Low",
        "Pre Month Low",

        "Pre Close CE",
        "Pre Close PE",

        "BEP"

    ]


    for column in numeric_columns:

        if column in result.columns:

            result[column] = pd.to_numeric(
                result[column],
                errors="coerce"
            ).round(2)


    return result


# ============================================================
# FORMAT GAINER TABLE
# ============================================================

def format_gainer_table(
    df
):

    if df.empty:

        return df


    columns = [

        "Symbol",

        "Pre Open",

        "Prev Close",

        "% Change",

        "Open Strike",

        "Pre Close Strike",

        "Pre Day High",

        "Pre Week High",

        "Pre Month High",

        "Day High Status",

        "Week High Status",

        "Month High Status",

        "Pre Close CE",

        "Pre Close PE",

        "BEP"

    ]


    columns = [

        column

        for column in columns

        if column in df.columns

    ]


    result = df[
        columns
    ].copy()


    return result


# ============================================================
# FORMAT LOSER TABLE
# ============================================================

def format_loser_table(
    df
):

    if df.empty:

        return df


    columns = [

        "Symbol",

        "Pre Open",

        "Prev Close",

        "% Change",

        "Open Strike",

        "Pre Close Strike",

        "Pre Day Low",

        "Pre Week Low",

        "Pre Month Low",

        "Day Low Status",

        "Week Low Status",

        "Month Low Status",

        "Pre Close CE",

        "Pre Close PE",

        "BEP"

    ]


    columns = [

        column

        for column in columns

        if column in df.columns

    ]


    result = df[
        columns
    ].copy()


    return result


# ============================================================
# HEADER
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
# TOP RIGHT MANUAL REFRESH
# ============================================================

left_space, refresh_space = (
    st.columns([8, 2])
)


with refresh_space:

    if st.button(
        "🔄 Manual Refresh",
        use_container_width=True
    ):

        # ====================================================
        # IMPORTANT:
        # Store refresh time in IST
        # ====================================================

        st.session_state.last_updated = (
            get_ist_time()
        )


        # Clear cached market data

        st.cache_data.clear()


        # Refresh page

        st.rerun()


# ============================================================
# LOAD DATA
# ============================================================

with st.spinner(
    "Loading NSE pre-market data..."
):

    try:

        (
            equities,
            options,
            option_expiry
        ) = load_instruments()


        if option_expiry is None:

            st.error(
                "No future option expiry found."
            )

            st.stop()


        # ====================================================
        # TOP 5
        # ====================================================

        (
            top5_gainers,
            top5_losers
        ) = get_top5_premarket(
            options
        )


        # ====================================================
        # ADD DATA
        # ====================================================

        gainers_final = (
            add_levels_and_options(
                top5_gainers,
                equities,
                options,
                "gainer"
            )
        )


        losers_final = (
            add_levels_and_options(
                top5_losers,
                equities,
                options,
                "loser"
            )
        )


    except Exception as e:

        st.error(
            f"Dashboard error: {e}"
        )

        st.stop()


# ============================================================
# SUMMARY CARDS
# ============================================================

c1, c2, c3, c4 = (
    st.columns(4)
)


# ============================================================
# GAINERS
# ============================================================

with c1:

    st.metric(
        "TOP 5 GAINERS",
        len(gainers_final)
    )


# ============================================================
# LOSERS
# ============================================================

with c2:

    st.metric(
        "TOP 5 LOSERS",
        len(losers_final)
    )


# ============================================================
# EXPIRY
# ============================================================

with c3:

    st.metric(
        "OPTION EXPIRY",
        str(option_expiry)
    )


# ============================================================
# LAST UPDATED
# ============================================================

with c4:

    st.metric(
        "LAST UPDATED",
        st.session_state.last_updated.strftime(
            "%I:%M:%S %p"
        )
    )


# ============================================================
# TOP 5 GAINERS
# ============================================================

st.markdown(
    """
    <div class="section-title">
        🟢 TOP 5 GAINERS
    </div>
    """,
    unsafe_allow_html=True
)


if gainers_final.empty:

    st.warning(
        "No gainer data available."
    )

else:

    gainers_display = (
        format_gainer_table(
            gainers_final
        )
    )


    st.dataframe(
        gainers_display,

        use_container_width=True,

        hide_index=True,

        height=285,

        column_config={

            "Symbol":
                st.column_config.TextColumn(
                    "Symbol"
                ),

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

            "Pre Close Strike":
                st.column_config.NumberColumn(
                    "Pre Close Strike",
                    format="%.0f"
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
                )

        }
    )


# ============================================================
# TOP 5 LOSERS
# ============================================================

st.markdown(
    """
    <div class="section-title">
        🔴 TOP 5 LOSERS
    </div>
    """,
    unsafe_allow_html=True
)


if losers_final.empty:

    st.warning(
        "No loser data available."
    )

else:

    losers_display = (
        format_loser_table(
            losers_final
        )
    )


    st.dataframe(
        losers_display,

        use_container_width=True,

        hide_index=True,

        height=285,

        column_config={

            "Symbol":
                st.column_config.TextColumn(
                    "Symbol"
                ),

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

            "Pre Close Strike":
                st.column_config.NumberColumn(
                    "Pre Close Strike",
                    format="%.0f"
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
                )

        }
    )


# ============================================================
# FOOTER
# ============================================================

current_updated = (
    st.session_state.last_updated
)


st.markdown(
    f"""
    <div class="footer-text">

        NSE Pre-Market Data
        &nbsp;&nbsp; | &nbsp;&nbsp;

        Last Updated:
        <b>
        {current_updated.strftime("%I:%M:%S %p")}
        </b>
        &nbsp;&nbsp; | &nbsp;&nbsp;

        Time Zone:
        <b>IST</b>

    </div>
    """,
    unsafe_allow_html=True
)
