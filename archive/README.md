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

Unlike the 2026-08-20 archival, the refactor plan is superseded as a *plan*
while remaining the specification of the running system. Read it when tracing
why a module is shaped the way it is; do not read it for what to do next.

`FINDINGS.md` and `HYPOTHESES.md` are never archived. They are append-only
research state and outlive every refactor — a wrong result is annotated in place,
not moved out of sight.
