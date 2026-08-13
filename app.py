import streamlit as st
import requests
import pandas as pd
from datetime import date, timedelta
from urllib.parse import quote


# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="NSE Pre-Market Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# NSE PRE-MARKET TIMING
# ============================================================
PRE_MARKET_OPEN = "09:00 AM"
PRE_MARKET_CLOSE = "09:08 AM"


# ============================================================
# CUSTOM CSS
# ============================================================
st.markdown(
    """
    <style>

    /* Remove Streamlit top padding */
    .block-container {
        padding-top: 1rem !important;
        padding-left: 1.2rem !important;
        padding-right: 1.2rem !important;
        max-width: 100% !important;
    }

    /* Hide Streamlit header */
    header[data-testid="stHeader"] {
        display: none;
    }

    /* Main title */
    .main-title {
        font-size: 30px;
        font-weight: 700;
        margin-bottom: 2px;
        line-height: 1.1;
    }

    /* Subtitle */
    .sub-title {
        color: #777;
        font-size: 15px;
        margin-top: 0;
        margin-bottom: 12px;
    }

    /* Section titles */
    .section-title {
        font-size: 22px;
        font-weight: 700;
        margin-top: 12px;
        margin-bottom: 8px;
    }

    /* Metric cards */
    div[data-testid="stMetric"] {
        border: 1px solid #dddddd;
        padding: 10px;
        border-radius: 10px;
        min-height: 95px;
    }

    /* Dataframe */
    div[data-testid="stDataFrame"] {
        width: 100% !important;
    }

    /* Reduce blank space */
    div[data-testid="stVerticalBlock"] {
        gap: 0.5rem;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# UPSTOX INSTRUMENT URL
# ============================================================
UPSTOX_INSTRUMENT_URL = (
    "https://assets.upstox.com/"
    "market-quote/instruments/exchange/NSE.json.gz"
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

    instruments["expiry_date"] = normalize_expiry(
        instruments["expiry"]
    )

    # NSE EQUITY
    equities = instruments[
        (instruments["segment"] == "NSE_EQ")
        &
        (instruments["instrument_type"] == "EQ")
    ].copy()

    # NSE OPTIONS
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

    nearest_expiry = future_expiries.min()

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

    chain = options[
        (options["underlying_symbol"] == symbol)
        &
        (options["instrument_type"] == option_type)
    ].copy()

    if chain.empty or pd.isna(price):

        return None

    chain["diff"] = (
        chain["strike_price"]
        - price
    ).abs()

    nearest = (
        chain
        .sort_values("diff")
        .iloc[0]
    )

    return int(
        nearest["strike_price"]
    )


# ============================================================
# OPTION INSTRUMENT KEY
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
        (options["instrument_type"] == option_type)
        &
        (options["strike_price"] == strike)
    ]

    if match.empty:

        return None

    return match.iloc[0]["instrument_key"]


# ============================================================
# NSE SESSION
# ============================================================
def nse_session():

    session = requests.Session()

    headers = {

        "User-Agent":
            "Mozilla/5.0",

        "Accept":
            "application/json,text/plain,*/*",

        "Accept-Language":
            "en-US,en;q=0.9",

        "Referer":
            "https://www.nseindia.com/"
            "market-data/"
            "pre-open-market-cm-and-emerge-market"
    }

    session.get(
        "https://www.nseindia.com",
        headers=headers,
        timeout=10
    )

    return (
        session,
        headers
    )


# ============================================================
# FETCH NSE PRE-MARKET DATA
# ============================================================
def fetch_nse_preopen_fo():

    session, headers = nse_session()

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

    for item in raw.get("data", []):

        metadata = item.get(
            "metadata",
            {}
        )

        rows.append({

            "Symbol":
                metadata.get("symbol"),

            "Prev Close":
                metadata.get("previousClose"),

            "IEP":
                metadata.get("iep"),

            "Change":
                metadata.get("change"),

            "% Change":
                metadata.get("pChange"),

            "Final":
                metadata.get("finalPrice"),

            "Final Quantity":
                metadata.get("finalQuantity"),

        })

    df = pd.DataFrame(rows)

    if df.empty:

        return df

    numeric_cols = [

        "Prev Close",
        "IEP",
        "Change",
        "% Change",
        "Final",
        "Final Quantity",

    ]

    for col in numeric_cols:

        df[col] = pd.to_numeric(
            df[col],
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
            "oi",
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

    hist = fetch_upstox_history(
        equity_key
    )

    if hist.empty:

        return None

    prev_day = hist.iloc[-1]

    prev_week = hist.tail(5)

    prev_month = hist.tail(20)

    return {

        "Pre Day High":
            prev_day["high"],

        "Pre Week High":
            prev_week["high"].max(),

        "Pre Month High":
            prev_month["high"].max(),

        "Pre Day Low":
            prev_day["low"],

        "Pre Week Low":
            prev_week["low"].min(),

        "Pre Month Low":
            prev_month["low"].min(),

    }


# ============================================================
# PREVIOUS OPTION CLOSE
# ============================================================
def get_prev_close(
    instrument_key
):

    if instrument_key is None:

        return None

    hist = fetch_upstox_history(
        instrument_key
    )

    if hist.empty:

        return None

    return hist.iloc[-1]["close"]


# ============================================================
# TOP 5 GAINERS / LOSERS
# ============================================================
def get_top5_premarket_with_strikes(
    options
):

    preopen = fetch_nse_preopen_fo()

    if preopen.empty:

        return (
            pd.DataFrame(),
            pd.DataFrame()
        )

    rows = []

    for _, row in preopen.iterrows():

        symbol = row["Symbol"]

        pre_open_price = row["IEP"]

        ce_strike = nearest_strike(
            options,
            symbol,
            "CE",
            pre_open_price
        )

        pe_strike = nearest_strike(
            options,
            symbol,
            "PE",
            pre_open_price
        )

        rows.append({

            "Symbol":
                symbol,

            "Pre Open":
                pre_open_price,

            "Prev Close":
                row["Prev Close"],

            "% Change":
                row["% Change"],

            "CE Strike":
                ce_strike,

            "PE Strike":
                pe_strike,

        })

    final = pd.DataFrame(rows)

    if final.empty:

        return (
            pd.DataFrame(),
            pd.DataFrame()
        )

    for col in [
        "Pre Open",
        "Prev Close",
        "% Change"
    ]:

        final[col] = pd.to_numeric(
            final[col],
            errors="coerce"
        ).round(2)

    gainers = (
        final
        .sort_values(
            "% Change",
            ascending=False
        )
        .head(5)
        .reset_index(drop=True)
    )

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
# ADD LEVELS + BEP
# ============================================================
def add_levels_and_bep(
    df,
    equities,
    options,
    side
):

    rows = []

    for _, row in df.iterrows():

        symbol = row["Symbol"]

        pre_open = row["Pre Open"]

        match = equities[
            equities["trading_symbol"]
            == symbol
        ]

        if match.empty:

            continue

        equity_key = (
            match
            .iloc[0]["instrument_key"]
        )

        levels = get_previous_levels(
            equity_key
        )

        if levels is None:

            continue

        ce_key = option_instrument_key(
            options,
            symbol,
            "CE",
            row["CE Strike"]
        )

        pe_key = option_instrument_key(
            options,
            symbol,
            "PE",
            row["PE Strike"]
        )

        pre_close_ce = get_prev_close(
            ce_key
        )

        pre_close_pe = get_prev_close(
            pe_key
        )

        # ====================================================
        # BEP
        # ====================================================
        bep = None

        if (
            pre_close_ce is not None
            and
            pre_close_pe is not None
        ):

            bep = (
                pre_close_ce
                +
                pre_close_pe
            ) / 2

        new_row = row.to_dict()

        # ====================================================
        # GAINER LEVELS
        # ====================================================
        if side == "gainer":

            new_row["Pre Day High"] = (
                levels["Pre Day High"]
            )

            new_row["Pre Week High"] = (
                levels["Pre Week High"]
            )

            new_row["Pre Month High"] = (
                levels["Pre Month High"]
            )

            new_row["Day High Status"] = (

                "abv"

                if pre_open
                > levels["Pre Day High"]

                else "--"
            )

            new_row["Week High Status"] = (

                "abv"

                if pre_open
                > levels["Pre Week High"]

                else "--"
            )

            new_row["Month High Status"] = (

                "abv"

                if pre_open
                > levels["Pre Month High"]

                else "--"
            )

        # ====================================================
        # LOSER LEVELS
        # ====================================================
        if side == "loser":

            new_row["Pre Day Low"] = (
                levels["Pre Day Low"]
            )

            new_row["Pre Week Low"] = (
                levels["Pre Week Low"]
            )

            new_row["Pre Month Low"] = (
                levels["Pre Month Low"]
            )

            new_row["Day Low Status"] = (

                "blw"

                if pre_open
                < levels["Pre Day Low"]

                else "--"
            )

            new_row["Week Low Status"] = (

                "blw"

                if pre_open
                < levels["Pre Week Low"]

                else "--"
            )

            new_row["Month Low Status"] = (

                "blw"

                if pre_open
                < levels["Pre Month Low"]

                else "--"
            )

        # ====================================================
        # OPTION CLOSE + BEP
        # ====================================================
        new_row["Pre Close CE"] = (
            pre_close_ce
        )

        new_row["Pre Close PE"] = (
            pre_close_pe
        )

        new_row["BEP"] = bep

        rows.append(new_row)

    result = pd.DataFrame(rows)

    if result.empty:

        return result

    number_cols = [

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

        "BEP",

    ]

    for col in number_cols:

        if col in result.columns:

            result[col] = pd.to_numeric(
                result[col],
                errors="coerce"
            ).round(2)

    return result


# ============================================================
# FORMAT TABLE
# ============================================================
def format_table(
    df,
    side
):

    if df.empty:

        return df

    display_df = df.copy()

    if side == "gainer":

        columns = [

            "Symbol",
            "Pre Open",
            "Prev Close",
            "% Change",

            "CE Strike",
            "PE Strike",

            "Pre Day High",
            "Pre Week High",
            "Pre Month High",

            "Day High Status",
            "Week High Status",
            "Month High Status",

            "Pre Close CE",
            "Pre Close PE",

            "BEP",

        ]

    else:

        columns = [

            "Symbol",
            "Pre Open",
            "Prev Close",
            "% Change",

            "CE Strike",
            "PE Strike",

            "Pre Day Low",
            "Pre Week Low",
            "Pre Month Low",

            "Day Low Status",
            "Week Low Status",
            "Month Low Status",

            "Pre Close CE",
            "Pre Close PE",

            "BEP",

        ]

    columns = [

        col

        for col in columns

        if col in display_df.columns

    ]

    return display_df[columns]


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
# LOAD DATA
# ============================================================
with st.spinner(
    "Loading NSE and Upstox data..."
):

    try:

        equities, options, opt_expiry = (
            load_instruments()
        )

        if opt_expiry is None:

            st.error(
                "No future option expiry found."
            )

            st.stop()

        top5_gainers, top5_losers = (
            get_top5_premarket_with_strikes(
                options
            )
        )

        gainers_final = (
            add_levels_and_bep(
                top5_gainers,
                equities,
                options,
                side="gainer"
            )
        )

        losers_final = (
            add_levels_and_bep(
                top5_losers,
                equities,
                options,
                side="loser"
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
c1, c2, c3, c4 = st.columns(4)


with c1:

    st.metric(
        "TOP 5 GAINERS",
        len(gainers_final)
    )


with c2:

    st.metric(
        "TOP 5 LOSERS",
        len(losers_final)
    )


with c3:

    st.metric(
        "OPTION EXPIRY",
        str(opt_expiry)
    )


with c4:

    # IMPORTANT:
    # Do NOT use datetime.now()
    # This is fixed to NSE pre-market close.
    st.metric(
        "PRE-MARKET CLOSE",
        PRE_MARKET_CLOSE
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

    gainers_display = format_table(
        gainers_final,
        "gainer"
    )

    st.dataframe(
        gainers_display,
        use_container_width=True,
        hide_index=True,
        height=300,
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

    losers_display = format_table(
        losers_final,
        "loser"
    )

    st.dataframe(
        losers_display,
        use_container_width=True,
        hide_index=True,
        height=300,
    )


# ============================================================
# FOOTER
# ============================================================
st.markdown("---")

st.caption(
    "NSE Pre-Market Session: "
    f"{PRE_MARKET_OPEN} – {PRE_MARKET_CLOSE}  |  "
    f"Data shown as of Pre-Market Close: "
    f"{PRE_MARKET_CLOSE}"
)
