# bs/visualisation.py
import numpy as np
import plotly.graph_objects as go
from scipy.interpolate import griddata

# griddata needs spread across T, otherwise the surface degenerates
MIN_EXPIRIES_FOR_SURFACE = 3


<<<<<<< HEAD
def visualize(df, S=None, title="IV surface"):
    """
    Build the IV figure from an already-filtered, IV-solved dataframe
    (output of prepare_quotes -> add_iv, optionally stitch_otm).
=======
def visualize(calls_df, S):
    calls_df = calls_df.copy()
    calls_df["moneyness"] = calls_df["strike"] / S
    filters = (
        (calls_df["mid_price"] > 0)
        & (calls_df["IV"].between(0.01, 1.3))
        & (calls_df["T"] >= 5 / 365)
        & (calls_df["moneyness"].between(0.8, 1.2))
    )
    t_calls_df = calls_df[filters].copy()
>>>>>>> e48d905e4142ac55ce6c2f5971e0adc8ae647b71

    Returns a plotly figure - the caller renders it (st.plotly_chart in the
    app, fig.show() in main.py). Falls back to 2D smiles when there are too
    few expiries for a meaningful surface.
    """
    df = df.copy()
    if "moneyness" not in df.columns:
        if S is None:
            raise ValueError("visualize needs a 'moneyness' column or scalar S")
        df["moneyness"] = df["strike"] / S
    df = df[df["IV"].between(0.01, 5)].dropna(subset=["IV"])

    if df.empty:
        fig = go.Figure()
        fig.update_layout(title=f"{title} - no valid points after filtering")
        return fig

    if df["expiration"].nunique() < MIN_EXPIRIES_FOR_SURFACE:
        return _smile_figure(df, title)
    return _surface_figure(df, title)


def _surface_figure(df, title):
    x = df["moneyness"].values
    y = df["T"].values
    z = df["IV"].values

    # create 2D space of evenly spaced data
    xi = np.linspace(x.min(), x.max(), 50)
    yi = np.linspace(y.min(), y.max(), 50)
    X, Y = np.meshgrid(xi, yi)
    # interpolation
    Z = griddata((x, y), z, (X, Y), method="linear")

    fig = go.Figure(data=[go.Surface(
        x=X, y=Y, z=Z,
        colorscale="Viridis",
        opacity=0.9,
    )])
    fig.update_layout(
        title=title,
        scene=dict(
            xaxis_title="Moneyness",
            yaxis_title="Time to expiry (in years)",
            zaxis_title="IV",
        ),
        height=700,
        margin=dict(l=0, r=0, t=40, b=0),
    )
    return fig


def _smile_figure(df, title):
    fig = go.Figure()
    for exp, grp in df.groupby("expiration"):
        grp = grp.sort_values("moneyness")
        fig.add_trace(go.Scatter(
            x=grp["moneyness"], y=grp["IV"],
            mode="lines+markers", name=str(exp),
        ))
    fig.update_layout(
        title=f"{title} - smile view (fewer than {MIN_EXPIRIES_FOR_SURFACE} expiries)",
        xaxis_title="Moneyness",
        yaxis_title="IV",
        height=500,
        margin=dict(l=0, r=0, t=40, b=0),
    )
    return fig
