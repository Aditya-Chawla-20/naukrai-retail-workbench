# Assessment requirements and acceptance

Source: Naukr.AI, *AI Retail Data & Conversational Intelligence Workbench*, DQ-AI-CHAT-03, pp. 1–5. Timebox: four calendar days. Expected effort: 12–18 focused hours. AI tools permitted. Review is automated and human.

| Brief | Implementation | Evidence |
|---|---|---|
| p. 2 · Persistent CSV runs, metadata and original/cleaned artifacts | Workbench + SQLite + immutable run directories | Batch result and per-run files |
| p. 2 · Before/after profiling, issue detection, planned deterministic cleaning, row/schema validation and stable rerun | Cleaning module and ledger; exact row counts and duplicates, estimated distinct count, parse failures, ranges and bounded frequency distribution | Run reports, plan IDs, original and cleaned CSVs, idempotency test |
| p. 2 · At least two retail capabilities | **Safe cross-dataset joins** and **sales analytics** | Unique catalog key, fan-out rejection, unmatched counts, revenue, average order value and unit return rate |
| p. 3 · Filter, sort, group, aggregate, compare, rank, distinct and descriptive statistics | Strict plan schema, authorized compiler and deterministic execution | Exact-input evaluator cases |
| p. 3 · Multi-turn retail reasoning, persisted traces, ambiguity and refusal | Run-pinned session scope and SQLite turn history | West return rate and status counts, clarification, refusal and original/cleaned version boundary |
| p. 4 · One shared, deterministic batch command | `python -m app.evaluate` uses Workbench and the same query engine | Complete batch JSON, artifacts and repeated-run comparison |
| p. 4 · Validation, privacy and bounded work | Type/size/path checks, cookie-scoped storage, allow-listed operators/joins, query limit and interrupt, no CSV values in hosted planning requests | Isolation, adversarial plans and other automated tests |
| p. 5 · **AI Engineering** specialization | NVIDIA planner → typed plan validation → application tool execution; local fallback, retries and exact-answer eval | Model-free eval and credentialed smoke report |
| p. 5 · Clean clone, meaningful commits, README, sample data, tests, env template | Locked Python project with Git history | Clean-clone log and README |
| p. 5 · 3–5 minute walkthrough | 3:37 captured browser walkthrough with synthesized narration | [Walkthrough](../walkthrough.mp4) |

The optional retail alternatives are product/category normalization and scoring/recommendations. Case variants are reported as data-quality issues. The submission chooses AI Engineering, one of the four offered specializations. The others are Full Stack, Backend/Data Engineering, and ML/Data Science.

## Scoring rubric

| Area | Points |
|---|---:|
| Data profiling and cleaning correctness | 18 |
| Retail-domain intelligence | 14 |
| Chat grounding and multi-turn reasoning | 20 |
| Safe execution and AI engineering | 12 |
| Batch evaluator and reliability | 10 |
| Architecture and code quality | 10 |
| Security, privacy and isolation | 6 |
| Automated tests | 5 |
| README and technical reasoning | 5 |
| **Total** | **100** |

The clean-clone gate requires a runnable evaluator, a readable cleaned artifact, a reproducible grounded chat answer, and visible isolation of a failed case. The assessment PDF provides the output contract and leaves the cases input shape open. The documented sample is the input contract validated here.
