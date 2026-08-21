# archive

Superseded documents and code, kept for provenance.

**Do not read this directory by default.** Nothing here is current, and nothing
here may be cited as evidence. Open it only when specifically asked, or when
tracing *why* something changed.

Naming: `<kind>/<NAME>_<YYYY-MM-DD>.md`, dated on the day it was superseded.

| path | superseded by | why |
| --- | --- | --- |
| `plan/PLAN_2026-08-20.md` | `plan/PLAN_2026-08-21.md` | single-strategy phase-gated plan, replaced by the alpha-lab architecture after the Phase 3 holdout FAIL and the Phase 4 resilience reversal |
| `plan/PLAN_2026-08-21.md` | `PLAN.md` | the **refactor plan** — the alpha-lab architecture, built out in full (stages A-E). Superseded once it was complete: it specified what to build, not how hard to run it, and left lab-level overfitting as an unresolved open decision. Still the referent of every "the refactor plan §N" citation in `src/`, and its non-negotiables and conventions are still in force |
| `agents/AGENTS_2026-08-20.md` | `AGENTS.md` | rewritten for the same refactor; the data gotchas and methodological lessons were carried forward, the phase gate was not |
| `plan/PLAN_2026-08-22.md` | `PLAN.md` | the **operating plan** — how throughput is rationed against a finite sample. Superseded by the discretionary pivot, but only in scope: its dispatch pipeline (§5), label-free pre-flight (§6), long-history extension (§8) and **both non-negotiables tables** remain in force. A `PLAN.md §5` or `§6` in a docstring written before 2026-08-22 means this document |
| `README_2026-08-22.md` | `README.md` | described the project as a Phase 0 / Phase 1 breakout screener. Superseded by `MISSION.md`: the project is a research laboratory for discretionary judgement, and the breakout screen is now one candidate generator among several |

Two of these are superseded in *scope* rather than in *content*, which is an
unusual state and worth naming. The refactor plan is no longer a plan but is
still the specification of the running system. The operating plan is no longer
the current plan but its budget discipline is still enforced by live code — the
dispatch gate, the pre-flight stage and the sample ledger all cite it. Read
either when tracing why a module is shaped the way it is; read neither for what
to do next.

`FINDINGS.md` and `HYPOTHESES.md` are never archived. They are append-only
research state and outlive every refactor — a wrong result is annotated in place,
not moved out of sight.
