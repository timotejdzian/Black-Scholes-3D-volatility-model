<!-- GUIDE_FOR_BEGINNERS.md -->

# The whole project, explained slowly from zero

This document assumes no background in options or in this codebase. It builds
every concept in order; each section uses only what came before it.

## 1. What an option is

A call option is a contract: the right, not the obligation, to BUY a stock at
a fixed price (the strike, K) on a fixed date (the expiration). A put option
is the same but the right to SELL. Example: a call on AAPL with strike 300
expiring July 17 lets you buy AAPL at 300 on that date. If AAPL is then at
320, the right is worth 20. If AAPL is at 280, the right is worth nothing -
you simply do not use it.

Options have market prices, quoted like stocks: a bid (what buyers offer)
and an ask (what sellers want). For each stock there are options at many
strikes and many expirations; the full set is called the option chain.

## 2. What the Black-Scholes formula does

Black-Scholes is a formula that computes a theoretical fair price of an
option from five inputs: the current stock price S, the strike K, the time
remaining until expiration T (in years), the risk-free interest rate r, and
the volatility sigma - how strongly the stock fluctuates. Four of the five
are known facts. Volatility is not: it is about the future, and nobody knows
the future.

## 3. What implied volatility is - the key inversion

So the formula is run backwards. The market already shows the option's price.
The question becomes: which sigma would make Black-Scholes produce exactly
that market price? That sigma is the implied volatility (IV). It is the
volatility the market collectively believes in, extracted from real prices.
There is no algebraic rearrangement of the formula for sigma, so the code
finds it numerically: try a sigma, compute the price, compare to the market,
adjust, repeat until they match (the `brentq` root-finder in
`bs/black_scholes.py` does this efficiently).

## 4. What the surface is

Compute IV for every strike and every expiration of one stock and you get
hundreds of numbers. Arrange them in 3D: one horizontal axis is moneyness
(strike divided by the stock level - 1.0 means the strike sits exactly at
the stock price, 0.8 means 20% below), the other horizontal axis is time to
expiration, and the vertical axis is IV. That shape is the volatility
surface. It is rarely flat: usually it curves up away from moneyness 1.0
(the "smile") and varies with maturity (the "term structure"). The shape is
information - it is how the market prices the risk of different scenarios.
This project computes that surface and lets you look at it.

## 5. What the program does, end to end

Step one, get data. Two sources exist side by side. Live mode asks Yahoo
Finance (through the `yfinance` library) for the current option chain and
the current stock price. Historical mode asks a free public database
(DoltHub, post-no-preference/options) that stores one end-of-day snapshot of
every chain for every US trading day back to 2019, and asks yfinance for
each day's closing stock price.

Step two, choose a price per option (`prepare_quotes`). The midpoint between
bid and ask is used, because it represents the current market. Options with
no bid, or with nonsense quotes (bid above ask), are thrown away. Filters
also remove options too far from the money or too close to expiration,
because their prices are unreliable.

Step three, solve (`add_iv`). For every surviving option, run the backwards
Black-Scholes search and store the IV.

Step four, draw (`visualisation.py`). The solved points are scattered
irregularly in (moneyness, T); a smoothing step (interpolation) stretches a
continuous surface over them, and Plotly renders it as the interactive 3D
plot you rotate in the app.

The Streamlit app (`app.py`) wraps these steps with controls: ticker box,
live/historical switch, a slider to scrub through historical days, filters,
and a log panel showing what every step did. Results are cached, so moving a
slider does not re-download or re-solve anything that was already done.

## 6. The problems we hit, retold slowly

The project's history is a sequence of subtle data problems. Each one is
worth understanding, because each is a general lesson about quantitative
work.

**The stale-price problem.** Originally the "market price" fed to the solver
was the last traded price. But an option that last traded at 11:00 carries
an 11:00 price even if the stock moved 2% by 16:00. The solver, given a
mismatched price and stock level, outputs a distorted IV without any error
message. Lesson: the solver never complains about wrong inputs; it encodes
them into the answer. Fix: use the live bid/ask midpoint, which is current
by definition, and drop options that have no real quotes.

**The timeout problem.** The first attempt at downloading history asked the
database for a whole month of rows in one query. The server allots each
query a small time budget; a month-sized question exceeded it and the server
gave up ("context deadline exceeded"), over and over, so the app loaded
forever. Fix: ask many small questions instead - one trading day at a time,
which the database answers quickly because that is exactly how its index is
organized. Each finished day is saved as its own CSV file, so an interrupted
download resumes where it stopped instead of starting over.

**The split problem (avoided, not suffered).** Stock data providers usually
"adjust" old prices for stock splits: after AAPL's 2020 4-for-1 split, the
adjusted history shows pre-2020 prices divided by 4. But the strikes stored
in the option database are the original, unadjusted numbers. Mixing adjusted
stock prices with unadjusted strikes would silently shift the whole surface
by a factor of 4 across the split date. The code therefore explicitly
requests unadjusted closes. Lesson: when joining two data sources, verify
they speak the same units.

**The trench - the most instructive bug.** One historical day showed a deep
canyon in the surface just below moneyness 1.0. The cause: the database's
option quotes had been captured while AAPL traded around 314, but the
official closing price said 307.75 - the quotes and the close described two
different moments of the day. The solver, told the stock was at 307.75,
looked at puts priced for a 314 stock and concluded they were bizarrely
cheap; the only way it could explain cheapness was to report absurdly low
volatility. Hence the trench, exactly in the options most sensitive to the
stock level (near the money, short maturity).

The diagnosis used a beautiful piece of theory called put-call parity: for
the same strike and expiry, the call price minus the put price pins down,
by pure arbitrage logic and with no model assumptions, what stock level the
market was actually using (technically its forward price F). Running that
calculation on the bad day showed the quotes "believed in" a stock 2.1%
above the close - the same offset at every maturity, the fingerprint of a
timing mismatch rather than anything economic.

The fix made the surface self-contained: instead of trusting an outside
closing price, the code now extracts F from the option quotes themselves
(per day, per expiration) and computes every IV and the moneyness axis
against that. The stock level and the option prices are now the same data
by construction, so this entire category of error cannot recur. Lesson:
when two sources must agree about a moment in time, prefer deriving the
quantity from one source over trusting their synchronization.

## 7. Honest limits of the result

The model prices European options (exercisable only at expiry) while US
stock options are American (exercisable any time). The difference matters
mostly for in-the-money options, so the default surface uses only
out-of-the-money ones, where the model is most honest. The interest rate is
a single constant although reality is a moving curve; for old data, set a
rate appropriate to that era in the sidebar. Historical data is one snapshot
per day - nothing intraday exists. The smooth surface between computed
points is interpolation, i.e. educated filling-in; jagged edges at the rim
are reconstruction artifacts, not market signals. And one operational rule:
if the most recent day looks strangely sparse, its file may have been
downloaded before the publisher finished uploading that day - delete that
one CSV in `bs/data_dolt/` and reload.

## 8. How to actually use it

Install once with `pip install -r requirements.txt`, start with
`streamlit run app.py`. Pick a ticker, choose Live or Historical. The first
historical load downloads day by day (progress appears in the terminal, not
the browser - expect minutes) and afterwards everything is instant from the
local files. Read the surface like a landscape: height is fear/expected
turbulence, the valley floor near moneyness 1.0 is the market's base
expectation, steep walls toward low moneyness show how much extra crash
protection costs. Use the date slider to watch the landscape deform through
time. The "Console logs" panel under each chart narrates the pipeline:
how many options came in, how many each filter removed and why, how many IVs
solved, and how the forward anchoring corrected the stock level - the same
numbers this guide just explained, live.

## 9. Small glossary

Spot (S): the current stock price. Strike (K): the fixed price in the option
contract. Expiration / T: the contract's end date / years remaining until
it. Moneyness: K divided by the stock level; 1.0 = at the money, below 1.0 =
strikes under the stock price. Bid / ask / mid: best buy offer, best sell
offer, their midpoint. Option chain: all listed options of one stock. IV:
the volatility implied by a market price through Black-Scholes. Surface: IV
plotted over (moneyness, T). Forward (F): the market-implied future stock
level for a given expiry, recoverable from option prices via put-call
parity. OTM / ITM: out of / in the money - whether exercising now would be
worthless or valuable. EOD: end of day.
