from src.discretionary.pa_adapter import PriceActionAdapter

def test_pa_adapter_truncation():
    adapter = PriceActionAdapter()
    case = adapter.render_case({"data": [1,2,3]})
    assert case["chart_bytes"] == b"fake_chart_bytes"
