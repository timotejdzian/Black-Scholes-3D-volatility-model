<!-- LIMITATIONS.md -->

# Imperfections: resolved, accepted, and lurking

Every model of option prices is wrong somewhere. This file records where this
one is wrong, what was done about it, and what to watch for. The ordering is
roughly the order in which the problems were discovered.

## Resolved during development

**Module-level execution in the data layer.** The original `get_data.py`
called the network at import time. Streamlit reruns the script on every
widget interaction, so this would have triggered an uncached fetch per click.
Removed; data functions now run only when called, behind caches.

**Last trade used as the price.** The original IV input was `lastPrice`. For
illiquid strikes that trade can be arbitrarily stale against the current
spot, producing IVs that are wrong in a way that looks like market structure.
Replaced by bid/ask mid with hard filters (bid > 0, ask > 0, bid <= ask).
The last-trade fallback survives only as an explicit, tagged, age-limited
option in live mode.

**T truncated to whole days.** `(exp - today).days / 365` yields T = 0 on
expiration day, and the formula divides by sqrt(T). Live T is now computed in
seconds to the 16:00 New York expiry. Historical T uses calendar days between
two end-of-day values, which is exact because both sides share the same time
of day.

**No dividend yield in the model.** `bs_price` originally had no q. The fix
added q, and then historical mode made it obsolete there: the parity-implied
forward already contains the market's dividend expectation, so q is forced to
0 in historical mode (anything else double-counts carry). q remains a manual
sidebar input for live mode only.

**DoltHub query timeouts.** Month-wide SELECTs with ORDER BY and growing
OFFSETs exceeded the API's per-query time budget ("context deadline
exceeded") and the app hung silently. All chain queries are now per single
trading day, matching the table's primary key prefix. Pagination advances by
rows actually received, so a server-side row cap cannot cause silent data
loss.

**Adjusted spot vs as-quoted strikes.** yfinance's default auto-adjusted
closes are back-shifted for splits; historical strikes are not. One flag
(`auto_adjust=False`) prevents moneyness from silently quadrupling across
AAPL's 2020 split, but the trap is worth recording because the corrupted
output would have looked plausible.

**Spot/quote desynchronization - the trench.** On 2026-06-05 the option
quotes implied a stock level 2.1% above the official close, constant across
expiries. Solving put IVs against the too-low close crushed sigma near the
money at short T into a visible trench; calls absorbed the same error as a
mild uniform lift and looked fine; raising q deepened the trench because it
pushed in the same direction as the error. Diagnosed with a model-free
put-call parity check (`check_forward.py`), fixed by anchoring each
(date, expiration) on its own implied forward. This class of bug is now
structurally impossible in historical mode.

**Date arithmetic across pandas versions.** `date + pd.Timedelta(...)`
returns different types on different pandas versions; one such expression
crashed only after the surrounding code was restructured to reach it.
Replaced with standard-library `timedelta`. General lesson: keep pandas out
of plain-date arithmetic.

**pyarrow dependency.** Existed only for parquet caching and caused install
trouble. Cache is plain CSV now; the read pins string dtypes on date columns
because CSV stores no types and pandas would otherwise guess Timestamps and
break the string-keyed joins.

## Accepted and labeled (know these before trusting the picture)

**Constant risk-free rate.** One sidebar r applies to every option on every
date. Reality is a curve that moved from ~0% (2020-2021) to >5% (2023). The
forward anchoring absorbs most of the damage in historical mode (F is
measured, not derived from r; r only discounts and seeds the parity formula,
where its sensitivity is small at short T). For long-dated options and deep
history, set a period-appropriate r manually. The proper fix - a per-date
yield curve joined from a rates database - is deferred but slots in cleanly
because r is passed per call, never hard-wired.

**American exercise vs European model.** US equity options are American;
Black-Scholes is European. The early-exercise premium is concentrated in ITM
options and near dividends. Mitigation, not solution: the default surface is
stitched OTM, where the premium is minimal. Calls-only and puts-only modes
will show seams and biases that are model error, not market information.

**EOD-only history; delayed live data.** The historical database is one
snapshot per trading day - intraday dynamics are invisible, and the snapshot
slider steps in days. Live yfinance quotes are ~15 minutes delayed and the
spot and chains are not captured in the same instant; live mode is not
parity-anchored, so a fast-moving market can produce small seams there.

**Interpolation artifacts.** The surface is `griddata` linear interpolation
over scattered points. Sparse wings produce faceting and jagged ridge lines;
those sawtooth edges are reconstruction artifacts, not volatility features.
With fewer than 3 expiries after filtering, no surface is drawn at all - the
app falls back to 2D smile lines, deliberately.

**The fallback forward.** When an expiration has fewer than 3 usable
call/put pairs (illiquid names, sparse far-dated chains), the anchor falls
back to close * e^(rT) and tags `forward_source="spot"`. Those expiries are
exposed to the desync class of error again. The tag is in the data; check it
when a single maturity looks off.

## Operational pitfalls (things that will bite, with the procedure)

**The most-recent cached day may be permanently partial.** Past days are
treated as immutable, but if a day was fetched before the publisher finished
uploading it, the incomplete chain is cached forever. Symptom: the latest
date's surface is sparse or misshapen while earlier dates are fine.
Procedure: delete `bs/data_dolt/{TICKER}_{date}.csv` for that day and reload.

**Ticker not in the database.** Coverage is ~2100 US symbols. A missing
symbol returns zero rows on every day, which looks like an endless fetch of
nothing. Procedure: `python -m bs.dolt_data TICKER`; step 1 returning 0 rows
is the verdict.

**Fetch progress is in the terminal, not the app.** The in-app log expander
captures the IV computation stage. Per-request fetch progress
(`[dolt] AAPL 2026-06-05: 1500 rows (12s)`) prints to the terminal running
`streamlit run`. A first load of a month is a few hundred sequential
requests against a free, rate-limited API: minutes, by design, once per
(ticker, day).

**Symbol conventions differ between sources.** Class shares are BRK-B on
yfinance and BRK.B on DoltHub. Translated automatically; relevant only if
the data layer is modified.

**Where each price-quality filter lives matters.** Zero-bid, crossed-quote,
moneyness and T filters all run in `prepare_quotes`, before the solver. If a
strike "disappears" from the surface, the log expander's drop counts say
which filter took it. ITM puts in EOD data routinely fail the no-arbitrage
lower bound and are dropped by the solver returning NaN; their absence below
moneyness 1.0 in puts-only mode is expected, not a bug.
