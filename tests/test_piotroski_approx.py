import pandas as pd

from src.research_data.pipelines import piotroski_approx
from src.research_data.sources import screener_fundamentals


def test_screener_parser_joins_only_common_regular_annual_periods():
    html = """
    <table><tr><th>x</th><th>Mar 2021</th><th>Mar 2022</th><th>TTM</th></tr>
      <tr><td>Sales +</td><td>100</td><td>120</td><td>130</td></tr>
      <tr><td>Operating Profit</td><td>10</td><td>15</td><td>16</td></tr>
      <tr><td>Net Profit +</td><td>7</td><td>9</td><td>10</td></tr>
      <tr><td>Dividend Payout %</td><td>10%</td><td>10%</td><td></td></tr>
    </table>
    <table><tr><th>x</th><th>Mar 2021</th><th>Mar 2022</th></tr>
      <tr><td>Equity Capital</td><td>10</td><td>10</td></tr>
      <tr><td>Borrowings +</td><td>20</td><td>15</td></tr>
      <tr><td>Other Liabilities +</td><td>50</td><td>52</td></tr>
      <tr><td>Other Assets +</td><td>80</td><td>90</td></tr>
      <tr><td>Total Assets</td><td>150</td><td>165</td></tr>
    </table>
    <table><tr><th>x</th><th>Mar 2021</th><th>Mar 2022</th></tr>
      <tr><td>Cash from Operating Activity +</td><td>8</td><td>12</td></tr>
    </table>
    """
    out = screener_fundamentals.parse(
        html, symbol="AAA", source_url="https://example.test/AAA",
        statement_scope="consolidated", fetched_at="2026-09-05")
    assert out["period_end"].tolist() == [pd.Timestamp("2021-03-31"),
                                          pd.Timestamp("2022-03-31")]
    assert out["operating_cash_flow"].tolist() == [8.0, 12.0]
    assert out["pit_status"].str.contains("not_point_in_time").all()


def test_approximate_score_exposes_components_and_six_month_lag():
    rows = []
    for year, values in [
        (2020, (100, 10, 5, 100, 20, 60, 40, 10, 6)),
        (2021, (120, 14, 8, 110, 18, 70, 42, 10, 10)),
        (2022, (150, 20, 12, 120, 15, 85, 44, 10, 15)),
    ]:
        rows.append(dict(zip(
            ["sales", "operating_profit", "net_income", "total_assets",
             "borrowings", "other_assets", "other_liabilities",
             "equity_capital", "operating_cash_flow"], values),
            symbol="AAA", period_end=pd.Timestamp(year, 3, 31),
            pit_status="current_restated_page_not_point_in_time"))
    out = piotroski_approx.score(pd.DataFrame(rows))
    latest = out.iloc[-1]
    assert latest["f_score_approx"] == 9
    assert latest["available_at_approx"] == pd.Timestamp("2022-09-30")
    assert all(pd.notna(latest[name]) for name in piotroski_approx.COMPONENTS)


def test_asof_never_exposes_score_before_approximate_availability():
    scores = pd.DataFrame({
        "symbol": ["AAA"], "period_end": [pd.Timestamp("2022-03-31")],
        "available_at_approx": [pd.Timestamp("2022-09-30")],
        "f_score_approx": pd.Series([8], dtype="Int8"),
    })
    out = piotroski_approx.asof(
        scores, [pd.Timestamp("2022-09-29"), pd.Timestamp("2022-09-30")])
    assert pd.isna(out.loc[out["session"] == "2022-09-29",
                           "f_score_approx"]).all()
    assert out.loc[out["session"] == "2022-09-30",
                   "f_score_approx"].iloc[0] == 8
