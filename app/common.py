"""Shared limits and storage utilities."""
import hashlib
import json
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from threading import BoundedSemaphore, Timer

import duckdb

MAX_FILES = 5
MAX_BYTES = 32 * 1024 * 1024  # Combined run budget, including normalized input.
MAX_ROWS = 500_000
MAX_COLUMNS = 64
MAX_PREVIEW = 25
SLOTS = BoundedSemaphore(2)


class Problem(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status

    def payload(self):
        return {"code": self.code, "message": str(self)}


def json_value(value):
    if isinstance(value, Decimal):
        return str(value)  # Exact, including currency amounts.
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def dump(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=json_value)


def json_data(value):
    return json.loads(dump(value))


def digest(*parts):
    return hashlib.sha256(dump(parts).encode()).hexdigest()


def quote(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def rows(cursor):
    columns = [c[0] for c in cursor.description]
    return json_data([dict(zip(columns, row)) for row in cursor.fetchall()])


@contextmanager
def slot():
    if not SLOTS.acquire(blocking=False):
        raise Problem("busy", "Two data operations are active. Try again shortly.", 503)
    try:
        yield
    finally:
        SLOTS.release()


@contextmanager
def database(path: Path, *, read_only=False):
    # Limit aggregate memory across the two process-wide slots. DuckDB's buffer
    # limit does not include all allocations. Keep input, work and result caps too.
    config = {
        "memory_limit": "256MB", "threads": "2", "max_temp_directory_size": "512MB",
        "enable_external_access": "false" if read_only else "true",
    }
    with duckdb.connect(str(path), read_only=read_only, config=config) as db:
        timer = Timer(8 if read_only else 45, db.interrupt)
        timer.daemon = True
        timer.start()
        try:
            yield db
        except duckdb.InterruptException as exc:
            raise Problem("query_timeout" if read_only else "run_timeout", "The operation exceeded its time budget.", 408) from exc
        except duckdb.OutOfMemoryException as exc:
            raise Problem("resource_limit", "The operation exceeded its memory or temporary disk budget.") from exc
        finally:
            timer.cancel()
            timer.join()
