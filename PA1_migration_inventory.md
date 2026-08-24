# PA1 Migration Inventory and Intraday Interfaces

## 1. Inventory

| Existing component | Action |
| --- | --- |
| `src/research_data/pipelines/opening.py` | To be generalised. Currently fetches one-second ticks and builds the opening window. Will be replaced by generic `intraday_panel` once built. |
| `src/research_data/pipelines/bulk_intraday.py` | To be archived/generalised. Currently reads fixed 1-minute datasets for H047. Will be replaced by the shared intraday API. |
| `src/research/families/opening_window/` | Retained as-is. Relies on `opening.py`. Its readers will be switched to `frame.load_intraday_panel` once the new interface demonstrates exact reproduction of existing inputs. |
| `src/research/families/bulk_deals/` | Retained as-is. Relies on `bulk_intraday.py`. Will transition similarly. |
| Direct parquet reads outside `research_data/` | Forbidden. Any such reads found will be moved behind `frame.py` before execution. |

## 2. Shared Intraday Interface (`frame.py`)

Added `load_intraday_panel` to `src/research_data/frame.py` which:
- Wraps the eventual versioned intraday store.
- Enforces `version` and `partition`.
- Takes `base_interval` and `derived_bars` arguments to standardize aggregation.
- Disallows ad-hoc direct access.

No parallel loader is planned.

