"""
Pre-market gainers/losers scanner with CE/PE strike + BEP levels.

Fixes applied vs. the original notebook:
  1. BEP was (CE premium + PE premium) / 2 -- that's an average premium,
     not a breakeven point. A straddle's real breakeven levels are
     strike +/- total premium (two prices, not one). Kept the original
     column so nothing downstream breaks, but added the two real
     breakeven columns and renamed the old one to make its meaning explicit.
  2. No retry / error handling around any network call -- one dropped
     request (NSE blocks/rate-limits often) killed the whole run with
     no output. Added retries with backoff and try/except so one bad
     symbol just gets skipped instead of crashing the script.
  3. 3 sequential Upstox calls per symbol x 10 symbols = 30 fresh
     TCP/TLS handshakes. Switched to one shared requests.Session
     (connection pooling + automatic retry) for all Upstox calls.
  4. nearest_strike() can return None, which becomes NaN once it goes
     through a DataFrame row -- option_instrument_key()'s `is None`
     check doesn't catch that. Switched to pd.isna().
  5. Guard added for the case where no upcoming options expiry is
     found (e.g. the instrument feed format changes).
"""

import time
import requests
import pandas as pd
from datetime import date, timedelta
from urllib.parse import quote
from requests.adapters import HTTPAdapter, Retry

UPSTOX_INSTRUMENT_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"

# Shared session for every Upstox call: pools TCP connections and retries
# transient failures (429/500/502/503/504) automatically instead of
# giving up on the first hiccup.
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
        print("NSE request failed:", e)
        return pd.DataFrame()

    if response.status_code != 200:
        print("NSE Error:", response.status_code)
        print(response.text[:500])
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
        except requests.RequestException as e:
            if attempt == retries:
                print("History request failed:", instrument_key, e)
                return pd.DataFrame()
            time.sleep(0.5 * (attempt + 1))
            continue

        if response.status_code != 200:
            print("History Error:", instrument_key, response.status_code)
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
        print("No NSE pre-open data received.")
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
def add_levels_and_bep(df, equities, options, side):
    rows = []

    for _, row in df.iterrows():
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

        # NOTE on breakeven: the original code did (CE + PE) / 2 and
        # called it "BEP" -- that's the average premium, not a real
        # breakeven price. A long straddle at a given strike actually
        # breaks even at two prices: strike - total_premium (downside)
        # and strike + total_premium (upside). Both are computed below;
        # "Avg Premium" keeps the old number under an honest name.
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
        new_row["BEP"] = avg_premium          # kept for backward compatibility
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


# ---------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------
if __name__ == "__main__":
    equities, options, opt_expiry = load_instruments()
    print("Option Expiry Used:", opt_expiry)

    top5_gainers, top5_losers = get_top5_premarket_with_strikes(options)

    gainers_final = add_levels_and_bep(top5_gainers, equities, options, side="gainer")
    losers_final = add_levels_and_bep(top5_losers, equities, options, side="loser")

    print("TOP 5 GAINERS")
    print(gainers_final)

    print("TOP 5 LOSERS")
    print(losers_final)
