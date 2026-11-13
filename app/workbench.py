"""Shared run, artifact and session service used by the API and evaluator."""
import hashlib
import json
import logging
import shutil
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import duckdb

from .cleaning import clean_table, mapped_fields, prepare_csv, role_for, ROLES
from .common import MAX_BYTES, MAX_FILES, MAX_ROWS, Problem, database, digest, dump, json_data, quote, slot

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Input:
    path: Path
    name: str
    role: str | None = None
    mapping: dict[str, str] = field(default_factory=dict)
    encoding: str = "utf-8-sig"


class Workbench:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self.store() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, request_hash TEXT NOT NULL,
                    idem TEXT, status TEXT NOT NULL, updated REAL NOT NULL, payload TEXT,
                    UNIQUE(owner, idem)
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, run_id TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0, context TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS turns (
                    session_id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(session_id, revision)
                );
            """)

    @contextmanager
    def store(self):
        with closing(sqlite3.connect(self.root / "metadata.sqlite3", timeout=5)) as db, db:
            db.row_factory = sqlite3.Row
            yield db

    def get_run(self, owner, run_id):
        with self.store() as db:
            row = db.execute("SELECT * FROM runs WHERE id=? AND owner=?", [run_id, owner]).fetchone()
        if row is None:
            raise Problem("run_not_found", "Run not found.", 404)
        return {"run_id": run_id, "status": row["status"], **json.loads(row["payload"] or "{}")}

    def list_runs(self, owner):
        with self.store() as db:
            return [dict(r) for r in db.execute(
                "SELECT id AS run_id, status FROM runs WHERE owner=? ORDER BY updated DESC LIMIT 30", [owner])]

    def ingest(self, owner, inputs, idem=None):
        if not 1 <= len(inputs) <= MAX_FILES:
            raise Problem("file_count", f"Upload between 1 and {MAX_FILES} CSV files.")
        if idem is not None and (not idem.strip() or len(idem) > 128):
            raise Problem("invalid_idempotency_key", "Use a nonempty idempotency key of up to 128 characters.")
        if sum(f.path.stat().st_size for f in inputs) > MAX_BYTES:
            raise Problem("upload_limit", "Combined upload exceeds 32 MiB.", 413)
        signatures, names = [], set()
        for item in inputs:
            if (Path(item.name).suffix.lower() != ".csv" or Path(item.name).name != item.name
                or not item.name.strip() or len(item.name) > 140
                or any(ord(c) < 32 or c in "\\/" for c in item.name)):
                raise Problem("invalid_filename", "Use a plain CSV filename.")
            if item.name.casefold() in names:
                raise Problem("duplicate_filename", "Give each CSV a distinct filename.")
            names.add(item.name.casefold())
            if item.role is not None and item.role not in ROLES:
                raise Problem("unknown_role", "Unsupported dataset role.")
            with item.path.open("rb") as fh:
                sha = hashlib.file_digest(fh, "sha256").hexdigest()
            signatures.append((item.name, item.role, sorted(item.mapping.items()), item.encoding, sha))
        request_hash = digest(signatures)
        with slot():
            with self.store() as db:
                db.execute("BEGIN IMMEDIATE")
                prior = db.execute("SELECT * FROM runs WHERE owner=? AND idem=?", [owner, idem]).fetchone() if idem else None
                if prior and prior["request_hash"] != request_hash:
                    raise Problem("idempotency_conflict", "This key was already used for different input.", 409)
                if prior and (prior["status"] != "running" or time.time() - prior["updated"] < 300):
                    return self.get_run(owner, prior["id"])
                # A stale process may have left a running entry. Publish its
                # replacement under a fresh ID, so their files never collide.
                if prior:
                    db.execute("UPDATE runs SET idem=NULL,status='failed',payload=? WHERE id=?", [
                        dump({"error": {"code": "interrupted", "message": "Run interrupted. A replacement was started."}}), prior["id"]])
                run_id = uuid.uuid4().hex
                db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,NULL)",
                           [run_id, owner, request_hash, idem, "running", time.time()])
            folder = self.root / run_id
            folder.mkdir()
            try:
                result = self._process(folder, inputs, signatures, request_hash)
            except (Problem, duckdb.Error, OSError) as exc:
                if not isinstance(exc, Problem):
                    logger.warning("Processing error for run %s (%s)", run_id, type(exc).__name__)
                issue = exc if isinstance(exc, Problem) else Problem("processing_error", "Could not process the CSV run.")
                self._finish(run_id, "failed", {"error": issue.payload()})
            except Exception:
                logger.exception("Unexpected processing error for run %s", run_id)
                self._finish(run_id, "failed", {"error": {"code": "internal_error", "message": "Run could not be completed."}})
            else:
                self._finish(run_id, "succeeded", result)
        return self.get_run(owner, run_id)

    def _finish(self, run_id, status, payload):
        with self.store() as db:
            db.execute("UPDATE runs SET status=?,updated=?,payload=? WHERE id=? AND status='running'",
                       [status, time.time(), dump(payload), run_id])

    def _process(self, folder, inputs, signatures, request_hash):
        datasets, total_rows, total_bytes = [], 0, 0
        with database(folder / "data.duckdb") as db:
            db.execute("CREATE TABLE cleaning_ledger (dataset VARCHAR PRIMARY KEY, plan JSON)")
            for index, item in enumerate(inputs, 1):
                dataset = f"d{index}"
                original = folder / f"{dataset}.original.csv"
                normalized = folder / f"{dataset}.import.csv"
                cleaned = folder / f"{dataset}.cleaned.csv"
                shutil.copyfile(item.path, original)
                with original.open("rb") as fh:
                    if hashlib.file_digest(fh, "sha256").hexdigest() != signatures[index - 1][-1]:
                        raise Problem("source_changed", "Input changed while copying. Retry with a stable file.")
                headers, count = prepare_csv(original, normalized, item.encoding)
                total_rows += count
                total_bytes += normalized.stat().st_size
                if total_rows > MAX_ROWS or total_bytes > MAX_BYTES:
                    raise Problem("input_limit", "Combined normalized input exceeds 500,000 rows or 32 MiB.")
                role = item.role or role_for(item.name)
                mapping = mapped_fields(headers, role, item.mapping)
                report = clean_table(db, dataset, normalized, headers, count, dataset, role, mapping)
                db.execute(f"COPY {quote(dataset)} TO ? (FORMAT CSV, HEADER true)", [str(cleaned)])
                normalized.unlink()
                datasets.append({"id": dataset, "name": item.name, "role": role,
                                 "version": digest("clean-v1", signatures[index - 1]), "mapping": mapping,
                                 "encoding": item.encoding, "sha256": signatures[index - 1][-1],
                                 "artifacts": {"original": original.name, "cleaned": cleaned.name}, **report})
        manifest = json_data({"version": digest("clean-v1", request_hash), "datasets": datasets})
        (folder / "report.json").write_text(dump(manifest), encoding="utf-8")
        return manifest

    def artifact(self, owner, run_id, name):
        run = self.get_run(owner, run_id)
        allowed = {"report.json"} | {artifact for item in run.get("datasets", []) for artifact in item["artifacts"].values()}
        if run["status"] != "succeeded" or name not in allowed:
            raise Problem("artifact_not_found", "Artifact not found.", 404)
        path = self.root / run_id / name
        if not path.is_file():
            raise Problem("artifact_not_found", "Artifact not found.", 404)
        return path

    def session(self, owner, run_id, session_id=None):
        if self.get_run(owner, run_id)["status"] != "succeeded":
            raise Problem("run_unavailable", "This run has no published cleaned data.", 409)
        if not session_id:
            session_id = uuid.uuid4().hex
            with self.store() as db:
                db.execute("INSERT INTO sessions (id,owner,run_id) VALUES (?,?,?)", [session_id, owner, run_id])
        with self.store() as db:
            row = db.execute("SELECT * FROM sessions WHERE owner=? AND id=? AND run_id=?",
                             [owner, session_id, run_id]).fetchone()
        if row is None:
            raise Problem("session_not_found", "Session not found for this run.", 404)
        return dict(row)

    def save_turn(self, session, context, payload):
        with self.store() as db:
            changed = db.execute(
                "UPDATE sessions SET context=?,revision=revision+1 WHERE id=? AND revision=?",
                [dump(context), session["id"], session["revision"]]).rowcount
            if not changed:
                raise Problem("session_conflict", "Another turn updated this session. Retry the question.", 409)
            db.execute("INSERT INTO turns VALUES (?,?,?)",
                       [session["id"], session["revision"] + 1, dump(payload)])

    def history(self, owner, run_id, session_id):
        self.session(owner, run_id, session_id)
        with self.store() as db:
            entries = db.execute("SELECT payload FROM turns WHERE session_id=? ORDER BY revision DESC LIMIT 50", [session_id]).fetchall()
        return [json.loads(e[0]) for e in reversed(entries)]
