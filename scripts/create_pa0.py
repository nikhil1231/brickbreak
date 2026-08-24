import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.contracts.dossier import MechanismDossier
from src.contracts.data_contract import DataContract, SourceFieldDef

def main():
    dossier = MechanismDossier(
        dossier_id="DOS_PA0_0000000001",
        hypothesis_id="H055",
        family="price_action",
        claim="Causal price structure plus contextual judgement identifies long opportunities whose future excess returns are better than strong, simple baselines by an economically useful amount after costs.",
        population="NSE EQ cash equities, ETFs excluded; initial 20-session median traded-value band of 3-25 crore.",
        expected_horizon_days=1,
        observable_facts=("hourly structure", "completed daily data through D-1", "five-minute decision bars", "next available five-minute bar open"),
        interpretation="Traders may react to remembered price regions; causal representation of those regions may contain information; context may determine which interactions matter.",
        causal_chain="A pivot or consolidation seed occurs -> nearby seeds merge under volatility-scaled rule -> later approaches, touches, rejections, breaks update -> resistance-to-support flip -> entry at next 5-min open.",
        counterparty="Traders reacting uniformly or predictably around remembered price regions.",
        counterparty_persistence_rationale="Cognitive limits, charting tool defaults, and institutional execution algorithms creating structural liquidity at certain levels.",
        competing_explanations=("Reversion to the mean.", "General momentum.", "Random walk with drift."),
        strongest_baseline="The full coded zone score without the AI contextual judge.",
        unique_predictions=("A frozen contextual judge improves on the strongest coded price-action baseline at the same take rate.",),
        natural_falsifiers=("Causal zone score fails to predict one-session-ahead excess return better than baseline.", "Contextual judge does not improve on coded baseline."),
        confounds=("Volatility contraction screens (H015 lookahead).", "Denominator lookaheads.", "Present-day size tier lookaheads."),
        capacity_notes="Intended position no more than 2% of lagged median daily traded value. 0.40% round trip cost floor.",
        min_effect_bps=80.0,
        nearest_hypothesis_ids=("H033", "H037", "H047"),
        required_observations_absent=("intraday_five_minute_bars", "intraday_hourly_bars"),
        memory_risk_classification="High memory risk; LLM may remember famous stock/date. H042 paired identity control required.",
        forward_confirmation_path="Untouched forward cases remain the decisive control.",
        proposer="Research Director",
        hostile_reviewer="Council Critics",
        required_feature_names=("zone_distance", "zone_overlap", "approach_speed", "approach_direction", "close_location", "rejection_strength", "prior_touch_count", "time_since_last_touch", "break_depth", "time_since_break", "lagged_time_of_day_volume_surprise", "completed_daily_trend", "completed_rolling_hour_trend", "distance_to_recent_highs_lows", "broad_market_context"),
        data_adapter="intraday_panel",
        entry_price="intraday",
        outcome_kind="market_excess",
        signal_kind="selector"
    )

    data_contract = DataContract(
        contract_id="DC_BREEZE_INTRADAY_001",
        source_name="Breeze Intraday",
        source_owner="ICICI Direct",
        licence_type="proprietary",
        cash_cost_usd=0.0,
        rate_limits="4-5 req/s safe",
        raw_fields=(
            SourceFieldDef("instrument_id", "string", "ISEC code", False),
            SourceFieldDef("symbol_asof", "string", "Point-in-time NSE ticker", True),
            SourceFieldDef("session", "string", "Trading date", True),
            SourceFieldDef("bar_start", "datetime", "Start time", True),
            SourceFieldDef("bar_end", "datetime", "End time", True),
            SourceFieldDef("available_at", "datetime", "When available", True),
            SourceFieldDef("open_raw", "float", "Raw open", True),
            SourceFieldDef("high_raw", "float", "Raw high", True),
            SourceFieldDef("low_raw", "float", "Raw low", True),
            SourceFieldDef("close_raw", "float", "Raw close", True),
            SourceFieldDef("volume_raw", "float", "Raw volume", True),
            SourceFieldDef("source", "string", "Source name", False),
            SourceFieldDef("source_interval", "string", "Interval", False),
            SourceFieldDef("request_id", "string", "Request ID", False),
            SourceFieldDef("quality_flags", "string", "Quality flags", False),
            SourceFieldDef("dataset_version", "string", "Dataset version", False),
        ),
        timestamp_tz="Asia/Kolkata",
        publication_latency_hours=0.0,
        available_at_rule="bar_end",
        first_tradable_session_rule="bar_end",
        coverage_start="2018-04-02",
        coverage_end="present",
        universe_depth="NSE EQ cash equities, ETFs excluded",
        survivorship_policy="Point-in-time daily captures from bhavcopy",
        expected_join_rate_pct=95.0,
        pagination_and_caps_notes="1,000-row hard cap, returns the TAIL. Chunk under 1,000 and assert the returned span.",
        entity_resolution_policy="NSE symbolchange.csv",
        unlocked_families=("price_action",),
        storage_path="data/metadata/research_store/director/contracts",
        maintenance_owner="Data Broker"
    )

    dossier_path = Path("data/metadata/research_store/dossiers") / f"{dossier.dossier_id}.json"
    dossier_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dossier_path, "w") as f:
        json.dump(dossier.to_dict(), f, indent=2)
    
    contract_path = Path("data/metadata/research_store/director/contracts") / f"{data_contract.contract_id}.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    with open(contract_path, "w") as f:
        json.dump(data_contract.to_dict(), f, indent=2)

    print("PA0 items generated successfully.")

if __name__ == "__main__":
    main()
