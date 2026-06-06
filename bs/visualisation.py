import pandas as pd
import numpy as np
from scipy.interpolate import griddata
import plotly.graph_objects as go


def visualize(calls_df, S):
    calls_df = calls_df.copy()
    calls_df["moneyness"] = calls_df["strike"] / S
    filters = (
        (calls_df["mid_price"] > 0)
        & (calls_df["IV"].between(0.01, 5))
        & (calls_df["T"] >= 5 / 365)
        & (calls_df["moneyness"].between(0.7, 1.3))
    )
    t_calls_df = calls_df[filters].copy()

    x = t_calls_df["moneyness"].values
    y = t_calls_df["T"].values
    z = t_calls_df["IV"].values

    # create 2D space of evenly spaced data
    xi = np.linspace(x.min(), x.max(), 50)
    yi = np.linspace(y.min(), y.max(), 50)
    X, Y = np.meshgrid(xi, yi)
    # interpolation
    Z = griddata((x, y), z, (X, Y), method="linear")

    # create the graph
    fig = go.Figure(data=[go.Surface(
        x=X, y=Y, z=Z,
        colorscale="Viridis",
        opacity=0.9
    )])

    fig.update_layout(
        scene=dict(
            xaxis_title="Moneyness",
            yaxis_title="Time to expiry (in years)",
            zaxis_title="IV",
        ),
        width=900,
        height=700,
    )

    fig.show(renderer="browser")