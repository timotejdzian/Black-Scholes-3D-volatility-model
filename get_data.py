from datetime import date, datetime
import pandas as pd 
import yfinance as yf


"""
S - spot price of the underlying asset xxx
Strike - Strike price - user chooses (can check the strike prices from stock_info("...") function) xxx
T - time to expiration (in years) xxx
r - 3.70, hardcoded, the differences are for our purposes negligable xxx 
option_type - calls/puts xxx
market_prices - price of the option 
"""


def get_option_data(stock_symbol, exp_date, option_type, strike):
    stock = yf.Ticker(stock_symbol)
    S = stock.fast_info["lastPrice"]
    chain = stock.option_chain(exp_date)
    options = getattr(chain, option_type)
    row = options[options["strike"] == strike]
    row = row.iloc[0]
    market_price = (row["bid"] + row["ask"])/2
    T = (datetime.strptime(exp_date,"%Y-%m-%d").date()-date.today()).days/365
    r = 0.037
    return S, strike, T, r, option_type, market_price



#Test data
stock_symbol = "Aapl"
exp_date ="2026-06-18"
option_type = "calls"
strike = 250

S, strike, T, r, option_type, market_price = get_option_data(stock_symbol, exp_date, option_type, strike)
# print(S, strike, T, r, option_type, market_price)