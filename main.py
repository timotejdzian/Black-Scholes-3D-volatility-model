from bs.get_data import get_option_data
from bs.black_scholes import add_iv, print_iv_sample
from bs.visualisation import visualize

if __name__ == "__main__":
    
    S, r, calls_df, puts_df = get_option_data("AAPL")
 
    calls_df = add_iv(calls_df, S, r, "call")
    puts_df = add_iv(puts_df, S, r, "put")
 
    min_T = 7 / 365
    atm_calls = calls_df[calls_df["strike"].between(S * 0.90, S * 1.10) & (calls_df["T"] >= min_T)]
    atm_puts = puts_df[puts_df["strike"].between(S * 0.90, S * 1.10) & (puts_df["T"] >= min_T)]
    print(f"\n[main] ATM+7d filter - calls: {len(atm_calls)}, puts: {len(atm_puts)}")
 
    print_iv_sample(atm_calls, "CALLS ATM")
    print_iv_sample(atm_puts, "PUTS ATM")

    visualize(calls_df, S)