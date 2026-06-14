#Put-call parity forward check against a cached DoltHub day file.
import sys
import numpy as np
import pandas as pd

day = sys.argv[1]
S = float(sys.argv[2])
r = 0.037

df = pd.read_csv(f"bs/data_dolt/AAPL_{day}.csv")
df["mid"] = (df["bid"] + df["ask"]) / 2
df = df[(df["bid"] > 0) & (df["ask"] > 0)]

for exp in sorted(df["expiration"].unique())[:4]:   # four nearest expiries
    d = df[df["expiration"] == exp]
    pairs = d[d["call_put"] == "Call"].merge(
        d[d["call_put"] == "Put"], on="strike", suffixes=("_c", "_p"))
    pairs = pairs[(pairs["strike"] / S).between(0.95, 1.05)]
    if len(pairs) < 3:
        print(f"{exp}: not enough near-ATM call/put pairs, skipped")
        continue
    T = (pd.Timestamp(exp) - pd.Timestamp(day)).days / 365
    F = pairs["strike"] + np.exp(r * T) * (pairs["mid_c"] - pairs["mid_p"])
    offset = F.median() - S * np.exp(r * T)
    print(f"{exp} (T={T:.3f}): implied forward {F.median():8.2f} | "
          f"spot-based forward {S * np.exp(r * T):8.2f} | offset {offset:+6.2f} "
          f"({100 * offset / S:+.2f}% of spot, {len(pairs)} pairs)")
