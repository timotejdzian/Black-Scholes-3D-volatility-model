# main.py
from bs.black_scholes import add_iv, prepare_quotes, print_iv_sample, stitch_otm
from bs.get_data import get_option_data
from bs.visualisation import visualize

if __name__ == "__main__":

    S, r, calls_df, puts_df = get_option_data("AAPL")

    calls_df = prepare_quotes(calls_df, S=S, use_last_fallback=False)
    puts_df = prepare_quotes(puts_df, S=S, use_last_fallback=False)

    calls_df = add_iv(calls_df, S, r, "call")
    puts_df = add_iv(puts_df, S, r, "put")

    print_iv_sample(calls_df[calls_df["moneyness"].between(0.9, 1.1)], "CALLS ATM")
    print_iv_sample(puts_df[puts_df["moneyness"].between(0.9, 1.1)], "PUTS ATM")

    surface_df = stitch_otm(calls_df, puts_df)
    fig = visualize(surface_df, S=S, title="AAPL OTM IV surface")
    fig.show(renderer="browser")
