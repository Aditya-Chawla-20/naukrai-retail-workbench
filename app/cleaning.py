"""CSV validation and auditable, row-preserving transformations."""
import csv
import re
from pathlib import Path

from .common import MAX_BYTES, MAX_COLUMNS, MAX_ROWS, Problem, digest, dump, quote, rows

ROLES = {"orders", "products", "inventory", "stores", "customers", "generic"}
FIELD_TYPES = {
    "units": "quantity", "returned_units": "quantity", "unit_price": "money",
    "revenue": "money", "stock": "quantity", "order_date": "date",
}
ALIASES = {
    "sku": ("sku", "product_id", "stock_code"),
    "category": ("category", "product_category"),
    "region": ("region", "store_region"),
    "units": ("units", "quantity"),
    "returned_units": ("returned_units", "return_quantity"),
    "unit_price": ("unit_price", "price"),
    "revenue": ("revenue", "sales", "total_amount"),
    "stock": ("stock", "stock_on_hand"),
    "order_date": ("order_date", "invoice_date", "ordered_at"),
    "order_id": ("order_id", "invoice_id"),
    "line_id": ("line_id", "order_line_id"),
}
SQL_TYPES = {"quantity": "BIGINT", "money": "DECIMAL(18,4)", "date": "DATE"}


def canonical(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower().strip()).strip("_")


def role_for(name):
    name = canonical(Path(name).stem)
    if name in {"order_lines", "order_items"}:
        return "orders"
    return name if name in ROLES else "generic"


def mapped_fields(headers, role, overrides):
    if role == "generic" and not overrides:
        return {}
    if set(overrides) - ALIASES.keys() or any(v not in headers for v in overrides.values()):
        raise Problem("invalid_mapping", "Mapping must connect a supported logical field to an exact CSV header.")
    if len(set(overrides.values())) != len(overrides):
        raise Problem("invalid_mapping", "Map each logical field to a different CSV column.")
    if any(key in headers and key != value for key, value in overrides.items()):
        raise Problem("invalid_mapping", "A logical field cannot override a different existing CSV header.")
    result = dict(overrides)
    for field, aliases in ALIASES.items():
        matches = [h for h in headers if canonical(h) in aliases and h not in result.values()]
        if field not in result and len(matches) == 1:
            result[field] = matches[0]
    return result


def prepare_csv(source, target, encoding):
    """Validate record widths before DuckDB sees input. Stream one record at a time."""
    if encoding not in {"utf-8-sig", "utf-8", "latin-1"}:
        raise Problem("unsupported_encoding", "Choose UTF-8 or explicitly declare Latin-1.")
    try:
        with source.open(encoding=encoding, newline="") as raw, target.open("w", encoding="utf-8", newline="") as clean:
            reader = csv.reader(raw, strict=True)
            headers = next(reader, [])
            if not headers or len(headers) > MAX_COLUMNS or any(
                not h.strip() or len(h) > 120 or any(ord(c) < 32 or ord(c) == 127 for c in h)
                for h in headers
            ):
                raise Problem("invalid_header", f"Expected 1–{MAX_COLUMNS} nonempty, printable CSV headers.")
            if len({h.strip().casefold() for h in headers}) != len(headers):
                raise Problem("invalid_header", "Duplicate or case-equivalent headers are ambiguous.")
            writer = csv.writer(clean, lineterminator="\r\n")
            writer.writerow(headers)
            count = 0
            for record in reader:
                if len(record) != len(headers) or any("\x00" in v for v in record):
                    raise Problem("malformed_csv", f"Unexpected field count or NUL at CSV line {reader.line_num}.")
                count += 1
                if count > MAX_ROWS:
                    raise Problem("row_limit", f"CSV exceeds {MAX_ROWS:,} records.")
                writer.writerow(record)
                if clean.tell() > MAX_BYTES:
                    raise Problem("upload_limit", "Normalized CSV exceeds the input budget.", 413)
            return headers, count
    except UnicodeDecodeError as exc:
        raise Problem("invalid_encoding", "CSV is not valid in the declared encoding. Use UTF-8 or explicitly select Latin-1.") from exc
    except csv.Error as exc:
        raise Problem("malformed_csv", "Malformed quoting or a field exceeds the CSV field limit.") from exc


def parse_expr(column, kind):
    value = f"trim({column})"
    if kind == "date":
        # ISO only. Preserve local-date tokens until someone supplies a policy.
        return f"CASE WHEN regexp_full_match({value}, '[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}') THEN try_cast({value} AS DATE) END"
    pattern = r"-?[0-9]+" if kind == "quantity" else r"-?([0-9]+|[0-9]{1,3}(,[0-9]{3})+)(\.[0-9]{1,4})?"
    if kind == "money":
        value = f"regexp_replace({value}, '^\\$', '')"
    return f"CASE WHEN regexp_full_match({value}, '{pattern}') THEN try_cast(replace({value}, ',', '') AS {SQL_TYPES[kind]}) END"


def profile(db, table, headers, types):
    source = quote(table)
    fields = []
    for name in headers:
        col = quote(name)
        parsed = parse_expr(col, types[name]) if name in types else None
        fields.extend([
            f"count(*) FILTER (WHERE {col} IS NULL OR trim({col}) = '')",
            f"approx_count_distinct({col})",
            f"count(*) FILTER (WHERE {col} IS NOT NULL AND {col} <> trim({col}))",
            f"count(*) FILTER (WHERE nullif(trim({col}), '') IS NOT NULL AND ({parsed}) IS NULL)" if parsed else "0",
            f"count(*) FILTER (WHERE regexp_full_match(trim({col}), '-?(0|[1-9][0-9]*)(\\.[0-9]{{1,4}})?') "
            f"AND try_cast(trim({col}) AS DECIMAL(18,4)) IS NOT NULL)" if not parsed else "0",
        ])
        if parsed:
            fields.extend([f"min({parsed})", f"max({parsed})"])
    count, *stats = db.execute(f"SELECT count(*), {', '.join(fields)} FROM {source}").fetchone()
    unique = db.execute(f"SELECT count(*) FROM (SELECT DISTINCT * FROM {source})").fetchone()[0]
    values = iter(stats)
    columns = {}
    for name in headers:
        nulls, distinct, whitespace, failures, numeric = (next(values) for _ in range(5))
        col = {"physical_type": "VARCHAR", "logical_type": types.get(name, "text"), "nulls": nulls,
               "distinct_estimate": distinct, "whitespace": whitespace, "parse_failures": failures}
        if numeric:
            col["numeric_like_rows"] = numeric
        identifier = canonical(name)
        if numeric and numeric == count - nulls and identifier not in {"id", "sku", "zip", "postal_code"} and not identifier.endswith(("_id", "_code")):
            col["inferred_query_type"] = "money"
        if name in types:
            col.update(min=next(values), max=next(values))
        # Only include frequencies, never raw cell values, in generic profiles.
        if count and 0 < distinct <= 20:
            col["top_value_frequencies"] = [x[0] for x in db.execute(
                f"SELECT count(*) n FROM {source} WHERE {quote(name)} IS NOT NULL "
                f"GROUP BY {quote(name)} ORDER BY n DESC LIMIT 5").fetchall()]
        columns[name] = col
    return {"row_count": count, "column_count": len(headers), "duplicate_rows": count - unique, "columns": columns}


def key_issues(db, table, role, mapping):
    key = {"products": "sku", "orders": "line_id"}.get(role)
    if key not in mapping:
        return {}
    col = quote(mapping[key])
    found = rows(db.execute(
        f"SELECT count(*) FILTER (WHERE nullif(trim({col}), '') IS NULL) missing_keys, "
        f"count(nullif(trim({col}), ''))-count(DISTINCT nullif(trim({col}), '')) duplicate_keys FROM {quote(table)}"))
    return found[0]


def clean_table(db, table, normalized, headers, expected_rows, dataset, role, mapping):
    raw = table + "_raw"
    schema = {header: "VARCHAR" for header in headers}
    db.execute(
        f"CREATE TEMP TABLE {quote(raw)} AS SELECT * FROM read_csv(?, columns=?, header=true, "
        "auto_detect=false, delim=',', strict_mode=true, compression='none', parallel=false)",
        [str(normalized), schema],
    )
    types = {actual: FIELD_TYPES[logical] for logical, actual in mapping.items() if logical in FIELD_TYPES}
    before = profile(db, raw, headers, types)
    if before["row_count"] != expected_rows:
        raise Problem("row_validation", "CSV reader and data engine disagree on row count.")
    issues, plan, projection = [], [], []
    for name in headers:
        col = quote(name)
        stats = before["columns"][name]
        parsed = parse_expr(col, types[name]) if name in types else None
        expression = f"nullif(trim({col}), '')"
        if parsed:
            expression = f"coalesce(cast(({parsed}) AS VARCHAR), {expression})"
        count = db.execute(f"SELECT count(*) FROM {quote(raw)} WHERE {col} IS DISTINCT FROM ({expression})").fetchone()[0]
        if stats["whitespace"]:
            issues.append(issue(dataset, "outer_whitespace", name, stats["whitespace"]))
        if stats["parse_failures"]:
            issues.append(issue(dataset, "ambiguous_or_invalid_type", name, stats["parse_failures"], "unresolved"))
        if 0 < stats.get("numeric_like_rows", 0) < before["row_count"] - stats["nulls"] and not (
            canonical(name).endswith("_id") or canonical(name) == "sku"
        ):
            issues.append(issue(dataset, "mixed_numeric_text", name, stats["numeric_like_rows"], "unresolved"))
        if count:
            plan.append({"id": digest(dataset, "normalize", name)[:16], "fields": [name], "risk": "low" if not parsed else "medium",
                         "op": "normalize_declared_type" if parsed else "trim_outer_whitespace",
                         "source": "code", "reason": "Trim outer whitespace and normalize valid declared types. Preserve ambiguous values.",
                         "affected_rows": count, "status": "planned"})
        projection.append(f"{expression} AS {col}")
    if before["duplicate_rows"]:
        issues.append(issue(dataset, "exact_duplicates", None, before["duplicate_rows"], "unresolved"))
    # Persist the plan in DuckDB before executing it. The caller writes the
    # readable manifest after all datasets validate.
    db.execute("INSERT INTO cleaning_ledger VALUES (?, ?)", [dataset, dump(plan)])
    db.execute(f"CREATE TABLE {quote(table)} AS SELECT {', '.join(projection)} FROM {quote(raw)}")
    after = profile(db, table, headers, types)
    actual_headers = [r[0] for r in db.execute(f"DESCRIBE {quote(table)}").fetchall()]
    if before["row_count"] != after["row_count"] or actual_headers != headers:
        raise Problem("cleaning_validation", "Cleaning unexpectedly changed row count or headers.")
    for name, count in key_issues(db, table, role, mapping).items():
        if count:
            issues.append(issue(dataset, name, mapping["sku" if role == "products" else "line_id"], count, "unresolved"))
    for field in ("category", "region"):
        if field not in mapping:
            continue
        col = quote(mapping[field])
        variants = db.execute(
            f"SELECT count(*) FROM (SELECT lower({col}) FROM {quote(table)} WHERE {col} IS NOT NULL "
            f"GROUP BY lower({col}) HAVING count(DISTINCT {col}) > 1)").fetchone()[0]
        if variants:
            issues.append(issue(dataset, "case_variants", mapping[field], variants, "unresolved"))
    for step in plan:
        step["status"] = "applied"
    db.execute("UPDATE cleaning_ledger SET plan = ? WHERE dataset = ?", [dump(plan), dataset])
    return {"profile_before": before, "profile_after": after, "issues": issues, "cleaning_plan": plan,
            "validation": {"row_delta": 0, "schema_unchanged": True, "unresolved_issue_ids":
                           [i["id"] for i in issues if i["status"] == "unresolved"]}}


def issue(dataset, kind, field, count, status="addressed"):
    return {"id": digest(dataset, kind, field)[:16], "code": kind, "field": field, "count": count, "status": status}
