"""Credential-free batch runner. Each case uses the production service."""
import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from .chat import Decision, ask, offline
from .common import Problem, dump
from .query import Plan
from .workbench import Input, Workbench


def parse_inputs(case, base):
    datasets = case.get("datasets")
    if datasets is None and (case.get("dataset_path") or case.get("csv_path")):
        datasets = [case.get("dataset_path") or case.get("csv_path")]
    if isinstance(datasets, dict):
        datasets = [{"path": path, "role": role} for role, path in datasets.items()]
    if not isinstance(datasets, list) or not datasets:
        raise Problem("missing_inputs", "Provide a nonempty datasets list.")
    result = []
    for item in datasets:
        if isinstance(item, str):
            item = {"path": item}
        path = (base / item["path"]).resolve(strict=True)
        if not path.is_file():
            raise Problem("invalid_path", "Input must be a regular CSV file.")
        result.append(Input(path, item.get("name", path.name), item.get("role"),
                            item.get("mapping", {}), item.get("encoding", "utf-8-sig")))
    return result


def check_expectation(turn, expected):
    failures = []
    if "status" in expected and turn["status"] != expected["status"]:
        failures.append("unexpected turn status")
    if "preview" in expected and turn["answer"]["preview"] != expected["preview"]:
        failures.append("unexpected result preview")
    if "row_count_considered" in expected and (turn["trace"] or {}).get("row_count_considered") != expected["row_count_considered"]:
        failures.append("unexpected input row count")
    if "operation" in expected and expected["operation"] not in (turn["trace"] or {}).get("operations", []):
        failures.append("expected operation missing")
    if "error_code" in expected and turn.get("error", {}).get("code") != expected["error_code"]:
        failures.append("unexpected error code")
    return failures


def evaluate_case(case, index, workbench, base):
    case_id = case.get("id", f"case-{index}") if isinstance(case, dict) else f"case-{index}"
    result = {"case_id": case_id, "status": "error", "dataset": {}, "profile_before": {}, "issues": [],
              "cleaning_plan": [], "profile_after": {}, "validation": {}, "chat_evaluation": [], "artifacts": {}}
    try:
        if not isinstance(case, dict) or not isinstance(case_id, str):
            raise Problem("invalid_case", "A case must be an object with a text ID.")
        run = workbench.ingest("batch", parse_inputs(case, base))
        if run["status"] != "succeeded":
            result["error"] = run["error"]
            return result
        for item in run["datasets"]:
            key = item["id"]
            for attr in ("profile_before", "profile_after", "validation"):
                result[attr][key] = item[attr]
            for attr in ("issues", "cleaning_plan"):
                result[attr].extend({"dataset": key, **entry} for entry in item[attr])
            result["artifacts"][key] = {k: str(workbench.root / run["run_id"] / v) for k, v in item["artifacts"].items()}
        result["dataset"] = {"version": run["version"], "files": [
            {k: item[k] for k in ("id", "name", "role", "version", "sha256", "mapping")} for item in run["datasets"]
        ]}
        result["artifacts"]["report"] = str(workbench.root / run["run_id"] / "report.json")
        session_id = None
        assertions = []
        for i, spec in enumerate(case.get("chat_questions", case.get("questions", [])), 1):
            spec = {"question": spec} if isinstance(spec, str) else spec
            plan = Plan.model_validate(spec["plan"]) if "plan" in spec else None
            turn = ask(workbench, "batch", run["run_id"], spec["question"], session_id=session_id,
                       planner=lambda q, r, p: Decision(offline(q, r, p), "offline"), structured=plan)
            session_id = turn.pop("session_id")
            result["chat_evaluation"].append(turn)
            assertions.extend({"turn": i, "message": msg} for msg in check_expectation(turn, spec.get("expected", {})))
        result["status"] = "assertion_failed" if assertions else "ok"
        if assertions:
            result["assertions"] = assertions
    except (Problem, ValidationError, KeyError, TypeError, ValueError, OSError) as exc:
        if not isinstance(exc, Problem):
            exc = Problem("invalid_case", "Invalid evaluator input, path, or structured plan.")
        result["error"] = exc.payload()
    except Exception:
        result["error"] = {"code": "internal_error", "message": "Unexpected case error."}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        cases = payload.get("cases") if isinstance(payload, dict) and "cases" in payload else payload
        if isinstance(cases, dict):
            cases = [cases]
        if not isinstance(cases, list):
            raise ValueError("Expected an array or a cases object.")
        service = Workbench(args.artifacts_dir)
        results = [evaluate_case(c, i, service, args.input.resolve().parent) for i, c in enumerate(cases, 1)]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_name(args.output.name + ".tmp")
        temporary.write_text(dump(results) + "\n", encoding="utf-8")
        temporary.replace(args.output)
        print(f"Wrote {len(results)} case results to {args.output}. "
              f"{sum(r['status'] == 'ok' for r in results)} succeeded.")
        return 0
    except (OSError, ValueError) as exc:
        print(f"Evaluation input/output error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
