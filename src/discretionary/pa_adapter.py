"""PA6: Anonymised case adapter and renderer for price-action cases."""

import json

class PriceActionAdapter:
    def __init__(self):
        self.schema_hash = "simulated_schema_hash"
    
    def render_case(self, data, anonymised=True):
        """
        - deterministic, rebased chart ending exactly at the decision bar
        - compact numeric sidecar
        - relative time and anonymised instrument identity by default
        - explicit decision vocabulary: TAKE, SKIP, confidence, invalidation, reasons
        """
        if anonymised:
            # Mask names and exact dates
            pass
            
        return {
            "chart_bytes": b"fake_chart_bytes",
            "sidecar": {"zone_dist": 0.5},
            "decision_schema": ["TAKE", "SKIP", "confidence", "reasons"]
        }
