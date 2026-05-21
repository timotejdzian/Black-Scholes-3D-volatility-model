import pandas as pd
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq

def bs_price(S, K, T, r, sigma, option_type):
    if T <= 0 or sigma <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == "call":
        return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)


def calc_iv(market_price, S, K, T, r, option_type):
    if T <= 0 or market_price <= 0:
        return np.nan
    intrinsic = max(0, S - K) if option_type == "call" else max(0, K - S)
    if market_price <= intrinsic:
        return np.nan
    try:
        return brentq(
            lambda sigma: bs_price(S, K, T, r, sigma, option_type) - market_price,
            1e-6, 10.0, xtol=1e-6, maxiter=500
        )
    except ValueError:
        # brentq raises ValueError when f(a) and f(b) have the same sign - no root in bracket
        return np.nan
    except RuntimeError:
        # brentq raises RuntimeError when maxiter exceeded without convergence
        return np.nan

def add_iv(df, S, r, option_type):
    print(f"\n[iv] calculating IV for {len(df)} {option_type} contracts...")
    df = df.copy()
 
    try:
        df["mid_price"] = df["lastPrice"]
    except KeyError as e:
        print(f"[iv] ERROR - missing bid/ask columns: {e}")
        raise
 
    df["IV"] = df.apply(
        lambda row: calc_iv(row["mid_price"], S, row["strike"], row["T"], r, option_type),
        axis=1
    )
 
    total = len(df)
    valid = df["IV"].notna().sum()
    failed = total - valid
    print(f"[iv] {option_type} results - valid: {valid}, failed/skipped: {failed} ({100*failed/total:.1f}%)")
 
    try:
        iv_valid = df["IV"].dropna()
        print(f"[iv] {option_type} IV range - min: {iv_valid.min():.4f}, max: {iv_valid.max():.4f}, median: {iv_valid.median():.4f}")
    except Exception as e:
        print(f"[iv] WARNING - could not compute IV stats: {e}")
 
    try:
        df["IV_yf"] = df["impliedVolatility"]
        df["IV_diff"] = df["IV"] - df["IV_yf"]
        yf_valid = df["IV_yf"].notna().sum()
        print(f"[iv] yfinance IV available for {yf_valid}/{total} contracts")
    except KeyError:
        print(f"[iv] WARNING - impliedVolatility column not present in yfinance data")
 
    return df

def print_iv_sample(df, label, n=5):
    has_yf = "IV_yf" in df.columns
    cols = ["expiration", "strike", "T", "mid_price", "IV"] + (["IV_yf", "IV_diff"] if has_yf else [])
    try:
        sample = (
            df[cols]
            .dropna(subset=["IV"])
            .query("IV > 0.01 and IV < 5.0")
            .head(n)
        )
    except KeyError as e:
        print(f"[print] ERROR - missing expected column: {e}")
        return
 
    if sample.empty:
        print(f"\n--- {label} - no valid contracts to display ---")
        return
 
    print(f"\n--- {label} (first {n} valid contracts) ---")
    sample = sample.copy()
    sample["T"] = sample["T"].map("{:.4f}".format)
    sample["mid_price"] = sample["mid_price"].map("{:.2f}".format)
    sample["IV"] = sample["IV"].map("{:.4f}".format)
    if has_yf:
        sample["IV_yf"] = sample["IV_yf"].map(lambda x: f"{x:.4f}" if pd.notna(x) else "n/a")
        sample["IV_diff"] = sample["IV_diff"].map(lambda x: f"{x:+.4f}" if pd.notna(x) else "n/a")
    print(sample.to_string(index=False))

