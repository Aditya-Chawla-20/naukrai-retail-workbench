# Evaluation and complete outputs

## Run from a clean clone

```sh
uv sync --locked
uv run --locked pytest -q
source .venv/bin/activate
python -m app.evaluate --input cases.json --output results.json --artifacts-dir ./evaluation_output
```

The mandatory evaluator is credential-free. See [cases.json](../cases.json) for sample input and exact assertions, and the [README](../README.md) for the input contract. The application revision under test was `d9715ab`.

## Observed results

| Case | Result | Exact check |
|---|---|---|
| West retail | Passed | Scope has 4 rows. Apparel return rate is 0.6 (3/5). Completed has 3 records. Weather is refused and unclear store ranking is clarified. |
| Query operations | Passed | East and West are distinct, typed filter/sort returns 10 then 6, regional gross sales are 1,000 each, bottom category is Home at 500, median units is 4, and raw/unknown-field requests are handled. |
| Malformed file | Expected error | CSV record 2 has too many fields. Error code `malformed_csv`. |
| Duplicate SKU | Passed | The case runs after the failure. Its unsafe query is rejected before a join can multiply revenue. |

- **Offline:** 4 cases, 13 chat turns, 3 successful case outcomes and 1 intentional ingestion failure. Two independent runs matched after removing instance-specific artifact paths. All published original, cleaned and report bytes matched. The saved snapshot rewrites only artifact paths to portable paths relative to the result file.
- **Automated:** 10 tests passed. They cover profiles, deterministic cleaning and idempotency, safe join/fan-out and missing keys, all-null and malformed/empty files, typed filtering and unsafe plans, ownership, exact follow-ups, injection, mocked model failure/retry, batch continuation and a 100,001-row fixture. Starlette emits one test-client deprecation warning.
- **Live NVIDIA:** Synthetic orders and products only. Nemotron 3.5 Lightning produced both exact analytic answers and the clarification without fallback. The explicit scope command ran locally. The session persisted all four turns and a separate cookie could not access the run. This is a targeted smoke test.
- **Walkthrough:** 216.629 seconds (3:37), 1280×800 H.264 with AAC. Decoded end to end with FFmpeg. Captured browser workflow and narrated with local synthesized speech.
- **Hidden grader:** pending reviewer execution. The assessment gives the output schema and CLI, and supplies no official input fixture in the provided files.

## Inspect the outputs

- [Clean-clone terminal output](evals/clean-clone.txt)
- [Complete offline batch result](evals/batch-results.json)
- [Live API output and assertions](evals/live-api.json)
- [West run original orders](evals/artifacts/west-retail/d1/original.csv), [cleaned orders](evals/artifacts/west-retail/d1/cleaned.csv), [original catalog](evals/artifacts/west-retail/d2/original.csv), [cleaned catalog](evals/artifacts/west-retail/d2/cleaned.csv) and [full run report](evals/artifacts/west-retail/report.json)
- [Query operations run report](evals/artifacts/query-operations/report.json) and [duplicate key run report](evals/artifacts/duplicate-key/report.json)
- [Three-minute walkthrough](../walkthrough.mp4)
