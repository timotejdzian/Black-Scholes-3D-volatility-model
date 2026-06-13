# bs/black_scholes.py
import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm


def bs_price(S, K, T, r, sigma, option_type, q=0.0):
    """Black-Scholes European price with continuous dividend yield q."""
    if T <= 0 or sigma <= 0:
        return np.nan
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))
    d2 = d1 - sigma * np.sqrt(T)
    if option_type == "call":
        return S * np.exp(-q * T) * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
    else:
        return K * np.exp(-r * T) * norm.cdf(-d2) - S * np.exp(-q * T) * norm.cdf(-d1)


def calc_iv(market_price, S, K, T, r, option_type, q=0.0):
    if T <= 0 or market_price <= 0:
        return np.nan
    # European lower bound (discounted intrinsic). Prices below it have no BS root.
    if option_type == "call":
        lower = max(0.0, S * np.exp(-q * T) - K * np.exp(-r * T))
    else:
        lower = max(0.0, K * np.exp(-r * T) - S * np.exp(-q * T))
    if market_price <= lower:
        return np.nan
    try:
        return brentq(
            lambda sigma: bs_price(S, K, T, r, sigma, option_type, q) - market_price,
            1e-6, 10.0, xtol=1e-6, maxiter=500,
        )
    except ValueError:
        # f(a) and f(b) have the same sign - no root in bracket
        return np.nan
    except RuntimeError:
        # maxiter exceeded without convergence
        return np.nan


def prepare_quotes(df, S=None, use_last_fallback=False, max_last_age_days=5,
                   moneyness_range=(0.7, 1.3), t_range=(5 / 365, 3.0)):
    """
    Filter BEFORE solving IV - brentq per row is the latency bottleneck.

    Price selection:
      - mid = (bid + ask) / 2 when bid > 0 and quote not crossed  -> price_source = "mid"
      - else, if use_last_fallback and lastPrice exists and the last trade
        is recent enough                                          -> price_source = "last"
      - else the row is dropped.

    Spot: per-row "spot" column when present (historical mode), else scalar S (live mode).
    """
    df = df.copy()
    n_in = len(df)

    if "moneyness" not in df.columns:
        spot = df["spot"] if "spot" in df.columns else S
        if spot is None:
            raise ValueError("prepare_quotes needs either a 'spot' column or scalar S")
        df["moneyness"] = df["strike"] / spot

    good_mid = (df["bid"] > 0) & (df["ask"] > 0) & (df["bid"] <= df["ask"])
    df["mid_price"] = np.where(good_mid, (df["bid"] + df["ask"]) / 2, np.nan)
    df["price_source"] = np.where(good_mid, "mid", "none")

    n_fallback = 0
    if use_last_fallback and "lastPrice" in df.columns:
        if "lastTradeDate" in df.columns:
            last_ts = pd.to_datetime(df["lastTradeDate"], utc=True, errors="coerce")
            df["last_trade_age_days"] = (pd.Timestamp.now(tz="UTC") - last_ts).dt.total_seconds() / 86400
            fresh = df["last_trade_age_days"] <= max_last_age_days
        else:
            fresh = pd.Series(True, index=df.index)
        use_last = ~good_mid & (df["lastPrice"] > 0) & fresh
        df.loc[use_last, "mid_price"] = df.loc[use_last, "lastPrice"]
        df.loc[use_last, "price_source"] = "last"
        n_fallback = int(use_last.sum())

    keep = (
        df["mid_price"].notna()
        & df["moneyness"].between(*moneyness_range)
        & df["T"].between(*t_range)
    )
    out = df[keep].copy()

    n_dropped_quotes = int((df["price_source"] == "none").sum())
    print(f"[prepare] {n_in} contracts in -> {len(out)} kept "
          f"(bad/zero quotes: {n_dropped_quotes}, last-price fallback used: {n_fallback}, "
          f"rest dropped by moneyness {moneyness_range} / T {tuple(round(t, 3) for t in t_range)})")
    return out


def add_iv(df, S, r, option_type, q=0.0):
    """Solve IV per contract. Expects df already passed through prepare_quotes."""
    print(f"\n[iv] calculating IV for {len(df)} {option_type} contracts...")
    df = df.copy()
<<<<<<< HEAD
    if df.empty:
        df["IV"] = pd.Series(dtype=float)
        return df

    has_spot_col = "spot" in df.columns
=======
 
    mid = (df["bid"].astype(float) + df["ask"].astype(float)) / 2
    if "lastPrice" in df.columns:
        last = df["lastPrice"].astype(float)
        df["mid_price"] = mid.where(mid > 0, last)
    else:
        df["mid_price"] = mid
 
>>>>>>> e48d905e4142ac55ce6c2f5971e0adc8ae647b71
    df["IV"] = df.apply(
        lambda row: calc_iv(
            row["mid_price"],
            row["spot"] if has_spot_col else S,
            row["strike"], row["T"], r, option_type, q,
        ),
        axis=1,
    )

    total = len(df)
    valid = df["IV"].notna().sum()
    failed = total - valid
    print(f"[iv] {option_type} results - valid: {valid}, failed/skipped: {failed} ({100 * failed / total:.1f}%)")

    iv_valid = df["IV"].dropna()
    if not iv_valid.empty:
        print(f"[iv] {option_type} IV range - min: {iv_valid.min():.4f}, "
              f"max: {iv_valid.max():.4f}, median: {iv_valid.median():.4f}")

    # reference IV: yfinance's impliedVolatility (live) or DoltHub's vol (historical,
    # renamed to impliedVolatility in dolt_data) - cross-check against our solver
    if "impliedVolatility" in df.columns:
        df["IV_ref"] = df["impliedVolatility"]
        df["IV_diff"] = df["IV"] - df["IV_ref"]
        print(f"[iv] reference IV available for {df['IV_ref'].notna().sum()}/{total} contracts")
    else:
        print("[iv] WARNING - no reference IV column present")

    return df


def anchor_to_forward(df, r, window=(0.95, 1.05), min_pairs=3):
    """
    Re-anchor a combined calls+puts chain on the forward the market itself
    implies, per (date, expiration): F = K + e^(rT) * (C_mid - P_mid), median
    over near-ATM pairs. Cures spot-vs-quote timing desyncs, absorbs dividends
    (no q guessing - F contains the market's carry), and collapses the
    call/put seam by parity construction.

    Sets: moneyness = K/F (forward moneyness), spot = F * e^(-rT) (the
    parity-consistent spot the IV solver should use with q = 0), forward,
    forward_source ("parity", or "spot" fallback when too few pairs).
    Original close is kept as spot_close.
    """
    df = df.copy()
    mid_ok = (df["bid"] > 0) & (df["ask"] > 0) & (df["bid"] <= df["ask"])
    df["_mid"] = np.where(mid_ok, (df["bid"] + df["ask"]) / 2, np.nan)
    df["spot_close"] = df["spot"]

    keys = ["date", "expiration"] if "date" in df.columns else ["expiration"]
    out = []
    offsets = []
    for _, g in df.groupby(keys):
        g = g.copy()
        S0 = g["spot_close"].iloc[0]
        T = g["T"].iloc[0]
        c = g[(g["option_type"] == "call") & g["_mid"].notna()][["strike", "_mid"]]
        p = g[(g["option_type"] == "put") & g["_mid"].notna()][["strike", "_mid"]]
        pairs = c.merge(p, on="strike", suffixes=("_c", "_p"))
        pairs = pairs[(pairs["strike"] / S0).between(*window)]
        if len(pairs) >= min_pairs:
            F = float((pairs["strike"] + np.exp(r * T) * (pairs["_mid_c"] - pairs["_mid_p"])).median())
            g["forward_source"] = "parity"
            offsets.append(F - S0 * np.exp(r * T))
        else:
            F = S0 * np.exp(r * T)
            g["forward_source"] = "spot"
        g["forward"] = F
        g["moneyness"] = g["strike"] / F
        g["spot"] = F * np.exp(-r * T)
        out.append(g)

    res = pd.concat(out, ignore_index=True).drop(columns=["_mid"])
    n_par = (res.groupby(keys)["forward_source"].first() == "parity").sum()
    n_all = res.groupby(keys).ngroups
    msg = f"[anchor] forward from parity for {n_par}/{n_all} expiries"
    if offsets:
        med = float(np.median(offsets))
        msg += f"; median forward offset vs close-implied: {med:+.2f}"
        if abs(med) > 0.005 * res["spot_close"].iloc[0]:
            msg += " (spot/quote desync detected and corrected)"
    print(msg)
    return res


def stitch_otm(calls_df, puts_df):
    """OTM surface: puts below spot, calls at/above spot. Minimal early-exercise premium."""
    otm_calls = calls_df[calls_df["moneyness"] >= 1.0]
    otm_puts = puts_df[puts_df["moneyness"] < 1.0]
    out = pd.concat([otm_puts, otm_calls], ignore_index=True)
    print(f"[stitch] OTM surface: {len(otm_puts)} puts (<1.0) + {len(otm_calls)} calls (>=1.0)")
    return out


def print_iv_sample(df, label, n=5):
    has_ref = "IV_ref" in df.columns
    cols = ["expiration", "strike", "T", "mid_price", "price_source", "IV"] + (
        ["IV_ref", "IV_diff"] if has_ref else []
    )
    cols = [c for c in cols if c in df.columns]
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
    if has_ref:
        sample["IV_ref"] = sample["IV_ref"].map(lambda x: f"{x:.4f}" if pd.notna(x) else "n/a")
        sample["IV_diff"] = sample["IV_diff"].map(lambda x: f"{x:+.4f}" if pd.notna(x) else "n/a")
    print(sample.to_string(index=False))