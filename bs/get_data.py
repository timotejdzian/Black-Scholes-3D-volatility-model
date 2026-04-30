from datetime import date, datetime
import pandas as pd 
import yfinance as yf


"""
S = spot price of the underlying stock
r = risk-free rate, hard-coded, for our purposes it is sufficient
calls_df = dataframe of call options containing contracts for every expiration 
puts_df = same but put
"""


def get_option_data(stock_symbol):
    stock = yf.Ticker(stock_symbol)
    S = stock.fast_info["lastPrice"]
    exp_dates = stock.options
    all_calls = []
    all_puts = []
    for exp in exp_dates:
        chain = stock.option_chain(exp)
        T = (datetime.strptime(exp, "%Y-%m-%d").date()-date.today()).days/365
        calls = chain.calls.assign(T=T, expiration=exp)
        puts = chain.puts.assign(T=T, expiration=exp)
        all_calls.append(calls)
        all_puts.append(puts)
    calls_df = pd.concat(all_calls, ignore_index=True)
    puts_df = pd.concat(all_puts, ignore_index=True)
    r = 0.037
    return S, r, calls_df, puts_df


S, r, calls_df, puts_df = get_option_data("Aapl")
