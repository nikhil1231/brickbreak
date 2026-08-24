# PA1 Migration Inventory and Intraday Interfaces

## 1. Inventory

| Existing component | Action |
| --- | --- |
| `src/research_data/pipelines/opening.py` | Retain until the generic product reproduces its frozen opening inputs exactly. Shared acquisition behaviour now lives in `pipelines/intraday.py`; reader migration has not yet happened. |
| `src/research_data/pipelines/bulk_intraday.py` | Retain until the generic product reproduces the H047 fixed-window inputs exactly. Do not archive before that measurement. |
| `src/research/families/opening_window/` | Retained as-is. Relies on `opening.py`. Its readers will be switched to `frame.load_intraday_panel` once the new interface demonstrates exact reproduction of existing inputs. |
| `src/research/families/bulk_deals/` | Retained as-is. Relies on `bulk_intraday.py`. Will transition similarly. |
| Direct parquet reads outside `research_data/` | Forbidden. Any such reads found will be moved behind `frame.py` before execution. |

## 2. Shared Intraday Interface (`frame.py`)

Added `load_intraday_panel` to `src/research_data/frame.py` which:

- refuses a missing or unhashed dataset rather than returning an empty frame;
- separates the intraday dataset version from its parent split version;
- always loads session identity before applying a partition, even if the caller
  requests only value columns;
- checks the frozen parent split hash and rejects registered outcome columns;
- reads only verified canonical parquet parts; and
- disallows ad-hoc direct access.

`src/research_data/pipelines/intraday.py` now owns frozen request manifests,
cap-safe chunking, immutable raw and normalised shards, resume state, dataset
assembly, and dataset hashes. Derived rolling-hour and causal-zone features are
computed from canonical five-minute bars; provider-specific hourly bars are not
part of the interface.

No parallel loader is planned.
