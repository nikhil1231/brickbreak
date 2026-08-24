from src.research_data.pipelines.causal_zones import build_zone_state_machine
import pandas as pd

def test_zone_state_machine_future_append():
    """Future append does not rewrite past state."""
    df1 = pd.DataFrame({"close": [100, 101, 102]})
    df2 = pd.DataFrame({"close": [100, 101, 102, 103]})
    out1 = build_zone_state_machine(df1)
    out2 = build_zone_state_machine(df2)
    pd.testing.assert_frame_equal(out1, out2.iloc[:3])
