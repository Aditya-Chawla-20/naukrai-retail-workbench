"""Typed query plans, authorized compilation and reproducible evidence."""
from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from .cleaning import FIELD_TYPES, parse_expr
from .common import MAX_PREVIEW, Problem, quote, rows

Name = Annotated[str, Field(min_length=1, max_length=120)]
Value = Annotated[str, Field(max_length=250)] | int | float | bool
Function = Literal["count", "distinct_count", "sum", "avg", "min", "max", "median", "stddev",
                   "gross_sales", "aov", "return_rate"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Filter(StrictModel):
    field: Name
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "is_null", "not_null"]
    value: Value | Annotated[list[Value], Field(min_length=1, max_length=25)] | None = None


class Metric(StrictModel):
    op: Function
    field: Name | None = None
    as_: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")] = "value"


class Sort(StrictModel):
    field: Name
    direction: Literal["asc", "desc"] = "asc"


class Plan(StrictModel):
    intent: Literal["aggregate", "select", "distinct", "compare", "scope", "clarify", "refuse"]
    dataset: Name | None = None
    join: Name | None = None  # Product dataset ID. All other join details are server-owned.
    filters: list[Filter] = Field(default_factory=list, max_length=8)
    context: Literal["replace", "extend"] = "replace"
    group_by: list[Name] = Field(default_factory=list, max_length=3)
    fields: list[Name] = Field(default_factory=list, max_length=8)
    metrics: list[Metric] = Field(default_factory=list, max_length=8)
    sort: list[Sort] = Field(default_factory=list, max_length=4)
    limit: int = Field(default=10, ge=1, le=MAX_PREVIEW)


def validate_join(db, fact, dim):
    if fact["role"] != "orders" or dim["role"] != "products" or fact["id"] == dim["id"]:
        raise Problem("unsafe_join", "Only orders → products by SKU is a supported join.")
    left, right = fact["mapping"].get("sku"), dim["mapping"].get("sku")
    if not left or not right:
        raise Problem("unsafe_join", "Declare the SKU columns on both datasets.")
    keys = rows(db.execute(
        f"SELECT count(*) FILTER (WHERE {quote(right)} IS NULL) missing, "
        f"count({quote(right)})-count(DISTINCT {quote(right)}) duplicates FROM {quote(dim['id'])}"))[0]
    if keys["missing"] or keys["duplicates"]:
        raise Problem("unsafe_join", "Product SKU must be unique and nonempty. Join rejected before execution.")
    on = f"a.{quote(left)} = b.{quote(right)}"
    join_sql = f" LEFT JOIN {quote(dim['id'])} b ON {on}"
    return join_sql, {"dataset": dim["id"], "version": dim["version"], "type": "left",
                      "cardinality": "many_to_one", "left_key": left, "right_key": right}


def run_query(db, run, plan):
    by_id = {x["id"]: x for x in run["datasets"]}
    if plan.dataset not in by_id or (plan.join is not None and plan.join not in by_id):
        raise Problem("unknown_dataset", "Select a dataset in this cleaned run.")
    table = by_id[plan.dataset]
    field_map, kinds, provenance = {}, {}, {}
    used = set()

    def register(item, alias, namespace=""):
        for raw, info in item["profile_after"]["columns"].items():
            expression = f"{alias}.{quote(raw)}"
            field_map[namespace + raw] = expression
            provenance[expression] = f"{item['name']}.{raw}"
            if info.get("inferred_query_type"):
                kinds[field_map[namespace + raw]] = info["inferred_query_type"]
        for logical, raw in item["mapping"].items():
            name = namespace + logical
            if name in field_map and field_map[name] != f"{alias}.{quote(raw)}":
                raise Problem("conflicting_mapping", "A logical field conflicts with an existing CSV header.")
            field_map[name] = f"{alias}.{quote(raw)}"
            if logical in FIELD_TYPES:
                kinds[field_map[name]] = FIELD_TYPES[logical]

    register(table, "a")
    join_sql, join = "", None
    if plan.join:
        dim = by_id[plan.join]
        join_sql, join = validate_join(db, table, dim)
        register(dim, "b", "product.")
        # Provide unqualified category only when the fact lacks it.
        if "product.category" in field_map:
            field_map.setdefault("category", field_map["product.category"])
        used.update({f"{table['name']}.{join['left_key']}", f"{dim['name']}.{join['right_key']}"})

    def resolve(field, *, typed=False):
        if field not in field_map:
            raise Problem("unknown_field", "A requested field is absent. Inspect the cleaned schema and field mappings.")
        col = field_map[field]
        used.add(provenance[col])
        return f"({parse_expr(col, kinds[col])})" if typed and col in kinds else col

    conditions, params = [], []
    for f in plan.filters:
        col = resolve(f.field, typed=True)
        if f.op in ("is_null", "not_null"):
            if f.value is not None:
                raise Problem("invalid_filter", "Null checks take no value.")
            conditions.append(f"{col} IS {'NOT ' if f.op == 'not_null' else ''}NULL")
            continue
        vals = f.value if isinstance(f.value, list) else [f.value]
        if not vals or any(v is None for v in vals) or (isinstance(f.value, list) != (f.op == "in")):
            raise Problem("invalid_filter", "Supply one value for a comparison or a list for IN.")
        kind = kinds.get(field_map[f.field])
        if not kind and any(not isinstance(v, str) for v in vals):
            raise Problem("invalid_filter", "Text comparisons require text values.")
        if kind == "date" and any(not isinstance(v, str) for v in vals):
            raise Problem("invalid_filter", "Date comparisons require ISO date strings.")
        if kind == "date":
            try:
                if any(date.fromisoformat(v).isoformat() != v for v in vals):
                    raise ValueError
            except ValueError as exc:
                raise Problem("invalid_filter", "Date comparisons require YYYY-MM-DD.") from exc
        if kind in ("money", "quantity") and any(type(v) not in (int, float) for v in vals):
            raise Problem("invalid_filter", "Numeric comparisons require numeric values.")
        if kind == "quantity" and any(type(v) is not int for v in vals):
            raise Problem("invalid_filter", "Quantity comparisons require whole numbers.")
        if f.op == "in":
            conditions.append(f"{col} IN ({','.join('?' for _ in vals)})")
        else:
            symbol = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[f.op]
            conditions.append(f"{col} {symbol} ?")
        params.extend(vals)
    source = f"FROM {quote(table['id'])} a{join_sql}"
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    considered = db.execute(f"SELECT count(*) {source}{where}", params).fetchone()[0]
    join_evidence = []
    if join:
        missing = f"b.{quote(join['right_key'])} IS NULL"
        left_key = f"a.{quote(join['left_key'])}"
        base = table["profile_after"]["row_count"]
        joined, unmatched, missing_keys = db.execute(
            f"SELECT count(*), count(*) FILTER (WHERE {missing}), "
            f"count(*) FILTER (WHERE {left_key} IS NULL) {source}").fetchone()
        if joined != base:
            raise Problem("unsafe_join", "Join changed the fact row count.")
        scoped_unmatched = db.execute(
            f"SELECT count(*) {source} WHERE {' AND '.join([*conditions, missing])}", params).fetchone()[0]
        join_evidence.append({**join, "fact_rows": base, "joined_rows": joined,
                              "unmatched_fact_rows": unmatched, "missing_fact_keys": missing_keys,
                              "scoped_unmatched_rows": scoped_unmatched})

    if plan.intent == "scope":
        if plan.metrics or plan.fields or plan.group_by or plan.sort or not plan.filters:
            raise Problem("invalid_plan", "A scope turn requires filters and cannot project or aggregate rows.")
        return [], evidence(run, table, used, plan, join_evidence, considered, 0, [], {})
    aggregating = plan.intent in ("aggregate", "compare")
    if aggregating and (not plan.metrics or plan.fields):
        raise Problem("invalid_plan", "Aggregation requires metrics and optional group fields.")
    if not aggregating and (not plan.fields or plan.metrics or plan.group_by):
        raise Problem("invalid_plan", "Select or distinct requires explicit fields.")
    if plan.intent == "compare" and not plan.group_by:
        raise Problem("invalid_plan", "A comparison needs at least one grouping field.")
    names = list(plan.group_by if aggregating else plan.fields)
    projection = [f"{resolve(name, typed=True)} AS {quote(name)}" for name in names]
    coverage_specs = {}
    components = {}
    operations = ["filter"] if conditions else []
    if join:
        operations.insert(0, "left_join")
    for metric in plan.metrics:
        expr, eligible = metric_expr(metric, table, field_map, kinds, resolve)
        projection.append(f"{expr} AS {quote(metric.as_)}")
        coverage_specs[metric.as_] = f"count(*) FILTER (WHERE {eligible})"
        names.append(metric.as_)
        operations.append(metric.op)
        if metric.op == "return_rate":
            for label, field in (("returned", "returned_units"), ("sold", "units")):
                alias = metric.as_ + "_" + label
                projection.append(f"sum({resolve(field, typed=True)}) FILTER (WHERE {eligible}) AS {quote(alias)}")
                names.append(alias)
                components[alias] = metric.as_
    if len({name.casefold() for name in names}) != len(names):
        raise Problem("invalid_plan", "Projection fields and metric aliases must be unique.")
    sorts = {s.field: s.direction for s in plan.sort}
    if set(sorts) - set(names) or len(sorts) != len(plan.sort):
        raise Problem("invalid_sort", "Sort by unique output fields.")
    order = [f"{quote(name)} {direction} NULLS LAST" for name, direction in sorts.items()]
    order.extend(f"{quote(name)} ASC NULLS LAST" for name in names if name not in sorts)
    group = " GROUP BY " + ", ".join(str(i) for i in range(1, len(plan.group_by) + 1)) if plan.group_by else ""
    distinct = "DISTINCT " if plan.intent == "distinct" else ""
    sql = f"SELECT {distinct}{', '.join(projection)} {source}{where}{group}"
    result = rows(db.execute(f"{sql} ORDER BY {', '.join(order)} LIMIT ?", [*params, plan.limit + 1]))
    coverage = (rows(db.execute(
        "SELECT " + ", ".join(f"{expr} AS {quote(name)}" for name, expr in coverage_specs.items()) + f" {source}{where}", params))[0]
        if coverage_specs else {})
    operations.extend([plan.intent, "order", "limit"])
    trace = evidence(run, table, used, plan, join_evidence, considered, len(result[:plan.limit]), operations, coverage)
    trace["truncated"] = len(result) > plan.limit
    if components:
        trace["metric_components"] = [{key: row[key] for key in [*plan.group_by, *components]} for row in result[:plan.limit]]
        for row in result:
            for key in components:
                del row[key]
    preview = result[:plan.limit]
    shortened = 0
    for table_rows in (preview, trace.get("metric_components", [])):
        for row in table_rows:
            for key, value in row.items():
                if isinstance(value, str) and len(value) > 400:
                    row[key] = value[:399] + "…"
                    shortened += 1
    trace["shortened_cells"] = shortened
    return preview, trace


def metric_expr(metric, table, fields, kinds, resolve):
    op = metric.op
    if op in ("gross_sales", "return_rate", "aov"):
        if table["role"] != "orders" or metric.field:
            raise Problem("invalid_metric", "Retail metrics require an orders dataset and use documented fields.")
        if any(i["code"] == "duplicate_keys" for i in table["issues"]):
            raise Problem("duplicate_fact_key", "Resolve duplicate order line IDs before computing retail metrics.")
        if op == "return_rate":
            units, returns = resolve("units", typed=True), resolve("returned_units", typed=True)
            eligible = f"{units} > 0 AND {returns} BETWEEN 0 AND {units}"
            return f"sum({returns}) FILTER (WHERE {eligible}) / nullif(sum({units}) FILTER (WHERE {eligible}), 0)", eligible
        if "units" in fields and "unit_price" in fields:
            units, price = resolve("units", typed=True), resolve("unit_price", typed=True)
            amount, eligible = f"{units} * {price}", f"{units} > 0 AND {price} >= 0"
        else:
            amount = resolve("revenue", typed=True)
            eligible = f"{amount} >= 0"
        total = f"sum({amount}) FILTER (WHERE {eligible})"
        if op == "aov":
            order = resolve("order_id")
            eligible += f" AND {order} IS NOT NULL"
            total = f"sum({amount}) FILTER (WHERE {eligible}) / nullif(count(DISTINCT {order}) FILTER (WHERE {eligible}), 0)"
        return total, eligible
    if not metric.field:
        if op == "count":
            return "count(*)", "true"
        raise Problem("invalid_metric", "This aggregation requires a field.")
    numeric = op in ("sum", "avg", "median", "stddev")
    if numeric and kinds.get(fields.get(metric.field)) not in ("money", "quantity"):
        raise Problem("invalid_metric", "This aggregation requires a mapped numeric field.")
    col = resolve(metric.field, typed=op not in ("count", "distinct_count"))
    if op == "distinct_count":
        return f"count(DISTINCT {col})", f"{col} IS NOT NULL"
    function = "stddev_samp" if op == "stddev" else op
    return f"{function}({col})", f"{col} IS NOT NULL"


def evidence(run, table, used, plan, joins, count, preview_rows, operations, coverage):
    return {"run_version": run["version"], "dataset": table["id"], "dataset_name": table["name"],
            "dataset_version": table["version"], "columns_used": sorted(used),
            "filters": [f.model_dump() for f in plan.filters], "joins": joins, "operations": operations,
            "row_count_considered": count, "preview_rows": preview_rows, "eligible_rows_by_metric": coverage}
