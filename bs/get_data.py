import sys
import time
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

"""
S = spot price of the underlying stock
r = risk-free rate, hard-coded default, sidebar-editable in the app
calls_df = dataframe of call options containing contracts for every expiration
puts_df = same but put
"""

DEFAULT_R = 0.037
EXPIRY_HOUR_UTC = 20


def get_option_data(stock_symbol):
    stock_symbol = stock_symbol.upper()
    stock = yf.Ticker(stock_symbol)
    S = stock.fast_info["lastPrice"]
    exp_dates = stock.options
    now = datetime.now(timezone.utc)

    all_calls = []
    all_puts = []
    for exp in exp_dates:
        chain = None
        for attempt in range(3):  # Yahoo rate-limits; retry with backoff
            try:
                chain = stock.option_chain(exp)
                break
            except Exception as e:
                print(f"[data] {stock_symbol} {exp}: {e}, retry {attempt + 1}", file=sys.stderr)
                time.sleep(2 ** attempt)
        if chain is None:
            continue
        exp_dt = datetime.strptime(exp, "%Y-%m-%d").replace(hour=EXPIRY_HOUR_UTC, tzinfo=timezone.utc)
        T = (exp_dt - now).total_seconds() / (365 * 24 * 3600)
        all_calls.append(chain.calls.assign(T=T, expiration=exp))
        all_puts.append(chain.puts.assign(T=T, expiration=exp))

    calls_df = pd.concat(all_calls, ignore_index=True)
    puts_df = pd.concat(all_puts, ignore_index=True)
    r = DEFAULT_R
    return S, r, calls_df, puts_df
