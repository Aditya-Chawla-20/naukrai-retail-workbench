# Retail Data Workbench

**Track: AI Engineering.** Profile and clean messy retail CSVs, then query a published version with an allow-listed plan whose answer can be reproduced. The browser, API and batch runner share the same workbench service.

## Clean-clone setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). From the repository root:

```sh
uv sync --locked
uv run --locked pytest -q
uv run --locked uvicorn app.api:app --host 127.0.0.1 --port 8000
```

Open [the workbench](http://127.0.0.1:8000) or [the API reference](http://127.0.0.1:8000/docs). Click **Try sample data**. Expand the orders dataset to inspect the difference between the input and output. Then ask:

1. `Only stores in the West region`
2. `Among those, which categories had the highest return rate?`
3. `Among those, which status has the most records?`

The second answer is Apparel at 60% (3 returned / 5 sold). The third is Completed with 3 order lines. Expand the evidence to inspect the selected data version, inherited filter, validated join, row count and metric components. Try `Which store is best?` for clarification. Upload `samples/orders.csv` and `samples/products_duplicate.csv` together and set upload metadata to `{"products_duplicate.csv":{"role":"products"}}` to reproduce a rejected join with `Show total revenue by category`.

[Watch the 3:37 walkthrough](walkthrough.mp4), made from captures of the running application with Andrew, a male neural narrator. It shows the cleaning run, unresolved date, ambiguous chat question, retail join, multi-turn evidence, and malformed-file recovery.

## Headless evaluation

```sh
source .venv/bin/activate
python -m app.evaluate --input cases.json --output results.json --artifacts-dir ./evaluation_output
```

The included batch has three successful cases and one intentional malformed CSV error. A bad case does not stop subsequent cases. Inspect each case status and per-turn assertions. A zero command exit code means the result document was written. An invalid top-level input or an output I/O failure returns code 2.

The PDF leaves the exact input shape open. Our input is an array of case objects or `{"cases": [...]}`. Each case uses an optional string `id`, a `datasets` list of CSV paths or objects with `path`, optional `name`, `role`, `mapping`, and `encoding`, and optional `chat_questions`. Paths are relative to the input JSON. The local evaluator trusts the invoking operator to choose input paths. It never uses case IDs as filesystem paths. A one-file case can also use `dataset_path` or `csv_path`. A dataset map from role to path is accepted.

Each chat turn can be a string or an object with `question`, optional structured `plan`, and optional `expected` assertions for `status`, exact `preview`, `row_count_considered`, `operation`, or `error_code`. The offline planner and injected plans use the same validator, executor, evidence formatter, and session store as the web service. Evaluation stays offline even with NVIDIA configured. IDs for issues, actions and data versions use stable content-derived hashes. Run and artifact location identifiers are instance-specific.

### API example

```sh
curl -sS -c cookies.txt -b cookies.txt \
  -F files=@samples/orders.csv -F files=@samples/products.csv \
  -H 'Idempotency-Key: demo-001' http://127.0.0.1:8000/api/runs
```

Use the returned `run_id` to POST `{"question":"Show total revenue by category"}` to `/api/runs/<run_id>/chat`, using the same cookie jar. Include the returned `session_id` for follow-ups. The structured `plan` input on that endpoint remains usable during a provider outage. See [the plan models](app/query.py) for allowed operations and the [sample cases](cases.json) for expected results.

## Data flow and boundaries

1. **Intake.** Copy and hash original bytes, validate headers and record widths in a streaming CSV pass, then stage data as text. Preserve identifiers such as `001`. Uploads default to UTF-8 (BOM accepted). Explicit Latin-1 is available. Both versions are available as downloadable files.
2. **Profile → plan → apply → validate.** Before and after profiles include physical and logical types, shape, nulls, exact duplicate count, approximate distinct counts, parse failures, ranges for typed fields and bounded value-frequency distributions. The cleaning ledger records stable IDs, reasons, fields, risk, affected rows, origin, and status. Verify row count and headers before publishing a run. Keep ambiguous dates, invalid numeric tokens, duplicates and unresolved category variants visible.
3. **Plan → validate → execute → answer.** A model or a limited offline planner selects a typed plan. Pydantic validates the shape. Server code authorizes datasets and validates fields, operators, types, projections, limits and joins. DuckDB executes parameterized queries with fixed operations and external access disabled. Code renders the answer from the computed rows. Every turn stores the question, resolved plan, result and trace in SQLite.
4. **Version and scope.** Each session is pinned to one run. A follow-up can extend the last successful filter scope or replace it. A new filter on the same logical field replaces its earlier value. Rejected and ambiguous turns preserve the previous scope. Concurrent changes to the same session use a revision check so one turn cannot silently overwrite another.

### Retail features

- **Safe cross-dataset joins.** The product catalog has one row per non-null SKU. The declared order-line → product relationship is a left many-to-one join. Validate catalog uniqueness before executing, then check joined row count and report missing and unmatched keys. Unmatched products form an uncategorized group. Resolve duplicate declared order-line IDs before computing named retail metrics.
- **Sales analytics.** Gross sales is the sum of positive units × nonnegative unit price where both exist, otherwise a mapped, nonnegative revenue column. AOV divides gross sales by distinct eligible order IDs. Unit return rate is returned units divided by sold units across valid rows (units > 0; 0 ≤ returned ≤ units). Missing inputs are excluded and coverage appears in the trace. A zero denominator is undefined. If the CSV has cancellations or multiple currencies, filter to an eligible population and one currency before interpreting a metric. Decimal currency results are strings to keep their precision. Sample files are synthetic with a single currency.

The sample grain is one order line per `line_id`; `order_id` can repeat. Product lookup uses `sku`. Retail mappings are inferred from unambiguous header aliases for known file roles, and can be overridden explicitly. Generic CSVs use exact headers, with conservative query-only numeric inference for fully numeric columns that look unlike identifiers. ISO dates and declared number formats are explicit. US thousands separators and a leading dollar sign are supported. Dates such as `03/04/2025` remain unresolved. Case-only category/region variants are flagged for review. Semantic alias merging, date reconciliation and broader warehouse modeling are intentionally outside the two chosen capabilities.

## NVIDIA planner

Offline mode is the default, with a documented limited question grammar. It handles the sample conversation, group/rank questions, distinct values, summaries, basic row selections, comparisons and simple `where field OP value` clauses. For other phrasings it can ask for clarification. Direct structured plans support the full operator set.

To enable the optional NVIDIA NIM adapter, copy `.env.example` to `.env`, set `NVIDIA_API_KEY`, and set `NVIDIA_MODEL` to a chat model ID available to your NVIDIA account. Try `nvidia/nemotron-3.5-lightning-30b-a3b`. Restart the server. The adapter calls the NVIDIA chat completions endpoint, requests a JSON plan, and uses strict local validation. Recognized explicit scope changes run locally so the next turn inherits the right population. Transient HTTP failures receive one bounded retry. Invalid output or an unavailable provider falls back to the offline planner with a visible reason. A structurally valid but unauthorized or unsafe plan is rejected. Automated tests use a fake transport. A live smoke test with `nvidia/nemotron-3.5-lightning-30b-a3b` reproduced the four-row West scope, 60% Apparel return rate, Completed count of 3 and a clarification on an ambiguous question in two runs. Model availability depends on account entitlement.

The hosted planner receives the user question, cleaned header names, role/field mappings, opaque **dataset-local** IDs, and the names of active filter fields. It receives zero CSV cell values, preview rows, file paths, filenames, or session IDs. Header names and user questions can themselves contain sensitive text. Keep hosted mode disabled for datasets with sensitive headers or users who would include personal data in questions. Keys stay server-side in environment variables and are never returned. The model never computes final numbers, sees hidden server state, or selects an authorization scope. Valid execution proves the reported computation; a plan can still misinterpret a question, which is why the eval asserts exact values and operations.

## Reliability and security

- Per-browser workspaces use a high-entropy HTTP-only, SameSite-strict cookie. Every run, artifact and session lookup is scoped server-side. Serve on loopback for the assessment. For a shared trusted deployment, use TLS, set `WORKBENCH_API_TOKEN` and `WORKBENCH_ALLOWED_HOSTS`, and put a real identity provider and request-rate limits in front before offering public multi-user access.
- Files are stored under generated run IDs. The browser escapes CSV text and outputs by setting text content. Treat CSV downloads as untrusted when opening in spreadsheets that interpret formulas.
- Combined run limits are five CSVs, 32 MiB normalized input, 500,000 rows and 64 columns per file. DuckDB uses two threads, a 256 MiB buffer target and a 512 MiB temp disk limit per operation. Two data operations run concurrently per process. These settings and the query interrupt are practical bounds on this assessment workload. Total process memory also depends on engine allocations, multipart spooling and worker count.
- Runs expose running, failed or succeeded state, plus structured errors. The HTTP request waits for a bounded cleaning operation on a worker thread. Files are private until the completed run is published through SQLite. An idempotency key deduplicates same-owner uploads and rejects different input. A stale in-progress key can start a fresh run after five minutes. Artifacts remain on disk for reproducibility. Use an operator-managed retention policy for longer-lived deployments.
- The engine never executes model-supplied SQL or Python. Queries have finite operators, depth, payload and result limits. The app logs internal failures without adding model prompts or credentials. Single-node deployment and local files are deliberate choices.

## Upstream references

- [TidySheet recipe model](https://github.com/rohanbeingsocial/tidysheet/blob/be10505/src/tidysheet/ir.py) informed the plan-before-mutation pattern.
- [AI E-commerce Analytics query compiler](https://github.com/Monokayser/ai-ecommerce-analytics/blob/7afb0be/src/data/query_engine.py) informed the typed compiler and bounded execution pattern.
- [Retail Intelligence Platform invariants](https://github.com/S-Harshni/Retail-Intelligence-Platform/blob/9138da0/sql/quality_checks.sql) informed join cardinality checks and exact-answer tests.
- The implementation and synthetic fixtures in this repository were written for this assessment.

## Submission evidence

[Open the submission report](submission-report.html) locally in a browser for the complete presentation. The [spec folder](spec/) includes the [requirement matrix](spec/requirements.md), [approach and trade-offs](spec/approach.md), [implementation log](spec/log.md) and [evaluation with saved outputs](spec/evals.md).
