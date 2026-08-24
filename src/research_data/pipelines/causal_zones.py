"""PA5: Causal zone and context features."""

import pandas as pd

def build_zone_state_machine(df: pd.DataFrame) -> pd.DataFrame:
    """
    Builds the support/resistance zone state machine.
    1. pivot or consolidation seed occurs
    2. knowable only after confirmation bars close
    3. nearby seeds merge under volatility-scaled rule
    4. approaches/touches/rejections/breaks update after bars close
    5. resistance-to-support flip on completed close confirm
    6. age, decay, corporate actions, invalidation deterministic
    """
    # Simulated skeleton
    df = df.copy()
    df["zone_distance"] = 0.5
    df["zone_overlap"] = 0.0
    df["prior_touch_count"] = 0
    return df
