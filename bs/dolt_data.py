# bs/dolt_data.py
"""
Historical EOD option chains from the DoltHub database post-no-preference/options
(table option_chain: date, act_symbol, expiration, strike, call_put, bid, ask,
vol, delta, gamma, theta, vega, rho), joined with UNADJUSTED daily closes from
yfinance for the spot.

The DoltHub API enforces a per-query time budget ("context deadline exceeded").
Month-wide queries with ORDER BY + OFFSET exceed it, so all chain queries are
per single trading day - that predicate matches the table's primary key prefix
(date, act_symbol, ...) and stays cheap.

Caching: one CSV per (symbol, trading day) under bs/data_dolt/. Past days are
immutable and never refetched; today is always refetched. An interrupted fetch
therefore resumes where it stopped.
"""
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

API_URL = "https://www.dolthub.com/api/v1alpha1/post-no-preference/options/master"
CACHE_DIR = Path(__file__).resolve().parent / "data_dolt"
PAGE = 500
COLUMNS = ["date", "expiration", "strike", "call_put", "bid", "ask", "vol"]


def to_dolt_symbol(symbol):
    # yfinance class shares use a dash (BRK-B), DoltHub uses a dot (BRK.B)
    return symbol.upper().replace("-", ".")


def to_yf_symbol(symbol):
    return symbol.upper().replace(".", "-")


def _query(sql, max_retries=4):
    for attempt in range(max_retries):
        try:
            resp = requests.get(API_URL, params={"q": sql}, timeout=90)
            if resp.status_code == 200:
                payload = resp.json()
                status = payload.get("query_execution_status")
                if status in ("Success", "RowLimit"):
                    return payload.get("rows", [])
                # includes "context deadline exceeded" - query hit the server time budget
                raise RuntimeError(payload.get("query_execution_message", f"status={status}"))
            if resp.status_code in (429, 500, 502, 503):
                raise RuntimeError(f"HTTP {resp.status_code}")
            resp.raise_for_status()
        except Exception as e:
            print(f"[dolt] query attempt {attempt + 1} failed: {e}", file=sys.stderr)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"DoltHub query failed after {max_retries} attempts")


def _fetch_day(dolt_symbol, day):
    """All contracts for one symbol on one trading day. Paginated; offset
    advances by rows actually received - robust to any server row cap."""
    frames = []
    offset = 0
    t0 = time.time()
    while True:
        sql = (
            f"SELECT {', '.join('`date`' if c == 'date' else c for c in COLUMNS)} "
            "FROM option_chain "
            f"WHERE act_symbol = '{dolt_symbol}' AND `date` = '{day}' "
            "ORDER BY expiration, strike, call_put "
            f"LIMIT {PAGE} OFFSET {offset}"
        )
        rows = _query(sql)
        if not rows:
            break
        frames.append(pd.DataFrame(rows))
        offset += len(rows)
        print(f"[dolt] {dolt_symbol} {day}: {offset} rows ({time.time() - t0:.0f}s)",
              file=sys.stderr)
        time.sleep(0.3)  # be polite to a free API
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    return pd.concat(frames, ignore_index=True)


def fetch_chain_history(symbol, trading_days):
    """Chain rows for the given trading days, using the per-day CSV cache."""
    dolt_symbol = to_dolt_symbol(symbol)
    CACHE_DIR.mkdir(exist_ok=True)
    today_iso = date.today().isoformat()

    frames = []
    for day in trading_days:
        path = CACHE_DIR / f"{dolt_symbol}_{day}.csv"
        if path.exists() and day != today_iso:
            part = pd.read_csv(path, dtype={"date": str, "expiration": str, "call_put": str})
            print(f"[dolt] cache hit {path.name} ({len(part)} rows)")
        else:
            part = _fetch_day(dolt_symbol, day)
            part.to_csv(path, index=False)
            print(f"[dolt] fetched + cached {path.name} ({len(part)} rows)")
        if not part.empty:
            frames.append(part)
        else:
            print(f"[dolt] WARNING - no chain rows for {symbol} on {day}")
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    return pd.concat(frames, ignore_index=True)


def fetch_spot_history(symbol, start, end):
    """UNADJUSTED daily closes. auto_adjust=True would back-adjust for splits
    (AAPL 4:1 in 2020) and silently shift moneyness against as-quoted strikes."""
    tk = yf.Ticker(to_yf_symbol(symbol))
    hist = tk.history(start=start.isoformat(),
                      end=(end + timedelta(days=1)).isoformat(),
                      auto_adjust=False)
    if hist.empty:
        raise RuntimeError(f"yfinance returned no price history for {symbol}")
    spot = hist["Close"].copy()
    spot.index = spot.index.tz_localize(None).strftime("%Y-%m-%d")
    spot.name = "spot"
    return spot


def get_historical_option_data(symbol, start, end):
    """
    Returns one dataframe with columns:
    date, expiration, strike, option_type, bid, ask, impliedVolatility (DoltHub's
    own IV, kept as reference), spot, T.

    Spot history is fetched FIRST; its index defines the trading days to query,
    so weekends/holidays cost zero API calls and every chain date has a spot
    by construction - no forward-filling anywhere.
    """
    spot = fetch_spot_history(symbol, start, end)
    trading_days = list(spot.index)

    chain = fetch_chain_history(symbol, trading_days)
    if chain.empty:
        raise RuntimeError(f"DoltHub returned no chain data for {symbol} in {start}..{end}")

    for col in ("strike", "bid", "ask", "vol"):
        chain[col] = pd.to_numeric(chain[col], errors="coerce")
    chain["option_type"] = chain["call_put"].str.lower()
    chain = chain.rename(columns={"vol": "impliedVolatility"}).drop(columns=["call_put"])

    df = chain.merge(spot, left_on="date", right_index=True, how="inner")

    # both sides are EOD values for the same trading day, so plain calendar
    # day difference is exact here
    df["T"] = (pd.to_datetime(df["expiration"]) - pd.to_datetime(df["date"])).dt.days / 365.0
    df = df[df["T"] > 0]

    print(f"[dolt] {symbol}: {len(df)} contracts across {df['date'].nunique()} dates "
          f"({df['date'].min()} .. {df['date'].max()})")
    return df.reset_index(drop=True)


if __name__ == "__main__":
    # connectivity self-test, independent of Streamlit:
    #   python -m bs.dolt_data AAPL
    sym = to_dolt_symbol(sys.argv[1] if len(sys.argv) > 1 else "AAPL")

    t0 = time.time()
    print(f"[selftest] 1/3 tiny query (5 rows) for {sym} ...")
    rows = _query(f"SELECT `date`, expiration, strike, call_put, bid, ask "
                  f"FROM option_chain WHERE act_symbol = '{sym}' LIMIT 5")
    print(f"[selftest] got {len(rows)} rows in {time.time() - t0:.1f}s")
    for row in rows:
        print("  ", row)
    if not rows:
        print(f"[selftest] WARNING - symbol {sym} returned nothing; it may not be in the database")

    t0 = time.time()
    print(f"[selftest] 2/3 latest available date for {sym} ...")
    latest = _query(f"SELECT MAX(`date`) AS d FROM option_chain WHERE act_symbol = '{sym}'")
    latest_day = str(latest[0]["d"])[:10]
    print(f"[selftest] latest date: {latest_day} ({time.time() - t0:.1f}s)")

    t0 = time.time()
    print(f"[selftest] 3/3 full single-day fetch for {latest_day} (the unit the app uses) ...")
    df = _fetch_day(sym, latest_day)
    print(f"[selftest] {len(df)} rows in {time.time() - t0:.1f}s - "
          f"multiply by ~21 trading days for a one-month first load")