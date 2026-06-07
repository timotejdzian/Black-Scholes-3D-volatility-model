<!-- README.md -->

# Black-Scholes IV Surface

Builds and visualizes implied volatility surfaces for US equity options, from
two data sources: live option chains (yfinance) and historical end-of-day
chains back to 2019 (the public DoltHub database post-no-preference/options).
The frontend is a Streamlit app with side-by-side comparison panels and a
snapshot-date slider for historical surfaces.

## Running it

```
pip install -r requirements.txt
streamlit run app.py        # the app
python main.py              # CLI path: one live AAPL surface in the browser
python -m bs.dolt_data AAPL # connectivity self-test for the historical source
```

## What an IV surface is, in one paragraph

The market price of an option implies a volatility: the sigma that makes the
Black-Scholes formula reproduce that price. Computing it for every strike and
expiration and plotting sigma over (moneyness, time to expiry) gives the IV
surface. Its shape - the smile across strikes, the term structure across
maturities - is how the market expresses its expectations about future
volatility, and deviations from a smooth shape are either market structure or
bugs. Much of this codebase exists to make sure they are not bugs.

## Module map and data flow

| File | Responsibility |
|---|---|
| `bs/get_data.py` | Live chains from yfinance. Spot from `fast_info`, every expiration's chain, retry with backoff, seconds-precision T. No code runs at import time. |
| `bs/dolt_data.py` | Historical chains from the DoltHub SQL API, one trading day per query, cached as one CSV per (ticker, day) in `bs/data_dolt/`. Joins an unadjusted daily close from yfinance. |
| `bs/black_scholes.py` | The model layer: `bs_price` (with dividend yield q), `calc_iv` (Brent root-finding), `prepare_quotes` (price selection and filtering), `anchor_to_forward` (put-call parity forward), `stitch_otm`, `add_iv`, diagnostics. |
| `bs/visualisation.py` | Turns a solved dataframe into a Plotly figure: 3D surface via `griddata` interpolation, or a 2D smile fallback when fewer than 3 expiries survive filtering. Returns the figure; never renders it itself. |
| `app.py` | Streamlit shell. Sidebar holds model parameters (r, q) and filters; each panel independently selects source, ticker, and surface mode. Three cache layers. Captures the modules' print diagnostics into a log expander. |
| `main.py` | Minimal CLI demonstrating the same pipeline without Streamlit. |
| `check_forward.py` | Standalone put-call parity diagnostic for a cached day file. |

The pipeline for every surface is the same four steps regardless of source:

1. fetch raw chain rows (plus a spot),
2. `prepare_quotes` - choose a price per contract and drop unusable rows,
3. `add_iv` - solve Black-Scholes for sigma per contract,
4. `visualize` - interpolate scattered (moneyness, T, IV) points onto a grid.

Historical mode inserts `anchor_to_forward` between steps 1 and 2.

## Design decisions and why

**Price = bid/ask mid, not last trade.** `lastPrice` is the most recent trade,
which for illiquid strikes can be hours or days old while the spot has moved.
Mid of a live bid/ask is the current market. Rows with zero or crossed quotes
are dropped. Live mode has an optional fallback to `lastPrice` for rows
without a usable quote; such rows are tagged `price_source="last"` with the
trade's age, and the app warns about their count, because mixing price
vintages on one surface must be a visible choice, not a silent one.

**Filter before solving.** Root-finding per contract is the latency
bottleneck. `prepare_quotes` applies the moneyness and T filters first, so
`calc_iv` runs only on contracts that can appear on the surface.

**Forward anchoring (historical mode).** The IV solver needs the stock level
that prevailed when the option quotes were captured. An external close can be
desynchronized from the chain snapshot (observed in practice: a constant +2.1%
offset across all expiries on one day, producing a put-IV trench near the
money). Put-call parity, C - P = (F - K)e^(-rT), recovers the forward the
quotes themselves imply, model-free. Per (date, expiration) the median F over
near-ATM pairs becomes the anchor: moneyness = K/F, solver spot = F e^(-rT),
q = 0 because F already contains the market's carry and dividend
expectations. The yfinance close is demoted to scaffolding: it defines the
trading calendar, seeds the ATM window for pair selection, and serves as a
fallback when an expiration has fewer than 3 usable pairs.

**Stitched OTM as the default surface.** US equity options are American;
Black-Scholes prices European exercise. The early-exercise premium
concentrates in in-the-money options, so the default surface uses OTM puts
below the forward and OTM calls above it. Calls-only and puts-only modes
remain selectable.

**Per-day queries against DoltHub.** The API enforces a per-query time
budget. Month-wide queries with ORDER BY and growing OFFSETs exceed it
("context deadline exceeded"); a single-day predicate matches the table's
primary key prefix and stays cheap. The trading-day list comes from the spot
history, so weekends and holidays cost zero requests.

**Per-day CSV cache.** One file per (ticker, day) gives resumable fetches
(every completed day is on disk), surgical invalidation (delete one file to
refetch one day), and simple freshness semantics (past days immutable, today
always refetched). CSV instead of parquet keeps pyarrow out of the
dependencies; the read pins string dtypes on date columns because CSV does
not store types.

**Unadjusted closes.** `yf.history(auto_adjust=False)`. Adjusted closes are
back-shifted for splits (AAPL 4:1 in 2020); historical strikes are as-quoted,
so adjusted spots would silently corrupt moneyness across every split
boundary in the data.

**T in seconds, never `days // 365` semantics.** Integer day counts truncate
to T = 0 on expiration day and Black-Scholes divides by sqrt(T). Live mode
computes T from the current timestamp to 16:00 New York on expiry; historical
mode uses calendar days between two same-time-of-day EOD values, which is
exact there.

**Caching in the app, three layers.** Live fetches cached 10 minutes;
historical fetches cached permanently per (ticker, window); the IV
computation cached per parameter set. Rotating a plot or toggling the log
expander therefore costs zero network calls and zero root-finding.

## Outputs worth knowing about

Every solved dataframe carries `IV` (this project's number), `IV_ref` (the
source's own IV: yfinance's `impliedVolatility` live, DoltHub's `vol`
historically) and `IV_diff`, as a permanent cross-check. The log expander in
each panel shows contract counts in and out of every filter, fallback usage,
solver failure rates, and the anchoring summary including the measured
forward offset.
