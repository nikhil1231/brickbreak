"""Fold the daily option files into the NIFTY index option chain."""
from src.research_data.pipelines import index_option_chain as ioc

if __name__ == "__main__":
    print("wrote", ioc.build(), flush=True)
