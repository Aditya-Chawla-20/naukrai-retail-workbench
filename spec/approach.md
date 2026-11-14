# Approach and trade-offs

1. **Use one service for reviewers and the browser.** FastAPI handles transport. The batch entry point invokes the same Workbench, chat orchestration and query executor directly. DuckDB handles tabular work, SQLite handles ownership, run status and sessions, and files hold downloadable artifacts.
2. **Stage text first.** Keep the original file bytes and content hash. Validate shape and encoding with a streaming CSV pass. Detect issues, persist the cleaning plan, apply safe transforms and compare row count and headers. Keep ambiguous dates, unexpected numeric tokens, duplicate rows and category variants available for inspection.
3. **Constrain retail joins and metrics.** Order lines join to a product catalog only by a declared SKU mapping. Validate uniqueness before the join and reconcile fact-row counts afterward. Return rate uses eligible returned units divided by eligible sold units, with numerator and denominator in the trace. Gross sales and order value use documented input fields and eligibility.
4. **Keep state server-side.** Pin each conversation to one cleaned run. Use explicit region commands for deterministic scope updates. A typed plan can extend or replace the last successful scope. Validate plan fields, filters, roles, join cardinality and query bounds before execution. Render answers from computed rows.
5. **Run evaluation credential-free.** Use a small deterministic planner and optional structured fixtures. Test exact data and operations alongside failures. Qualify hosted planning separately with synthetic inputs. Document the provider request contract in the [README](../README.md).

## Kept small

- Single-node, loopback-first deployment. SQLite and DuckDB are sufficient for the assessment and tested input ceiling. Cleaning runs in a bounded request worker, with durable running, succeeded and failed states. A distributed queue would add complexity for no measured need.
- One approved relationship and two retail capabilities. A conservative grammar provides a useful offline path. Free-form utterances can ask for clarification. Generic input is profiled and selection remains available, with conservative query-time numeric inference.
- An unresolved value stays inspectable. A human can correct the input or declare a mapping. The unit return rate excludes invalid numeric rows and displays coverage. Cancellation/discount/currency semantics depend on the dataset and documented scope.
- The hosted model can misinterpret natural language even when its plan is structurally valid. Tests assert intent, scope, and exact results. The live smoke cases cover the sample flow, not all possible questions.
- References from TidySheet, AI E-commerce Analytics and Retail Intelligence Platform informed the recipe, compiler and invariants. The implementation and checked-in fixtures were written for this assessment.
