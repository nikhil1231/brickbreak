"""Fold the daily option files into the banded stock option chain table."""
from src.research_data.pipelines import option_chain as oc

if __name__ == "__main__":
    print("wrote", oc.build(), flush=True)
