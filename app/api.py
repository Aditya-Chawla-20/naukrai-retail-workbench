"""FastAPI entry point with same-origin browser workspaces."""
import hashlib
import hmac
import json
import os
import re
import secrets
from pathlib import Path
from tempfile import TemporaryDirectory

from dotenv import load_dotenv
from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import Field
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .chat import ask
from .common import MAX_BYTES, MAX_FILES, Problem
from .query import Plan, StrictModel
from .workbench import Input, Workbench

STATIC = Path(__file__).with_name("static")
SAMPLES = STATIC.parent.parent / "samples"
COOKIE = "retail_workspace"
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")


class ChatRequest(StrictModel):
    question: str = Field(min_length=1, max_length=1500)
    session_id: str | None = Field(default=None, max_length=40)
    plan: Plan | None = None


def create_app(root=None, access_token=None):
    service = Workbench(root or os.getenv("WORKBENCH_DIR", ".workbench"))
    api = FastAPI(title="Retail Data Workbench", version="0.1.0")
    token = access_token if access_token is not None else os.getenv("WORKBENCH_API_TOKEN", "")
    allowed_hosts = os.getenv("WORKBENCH_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver")
    api.add_middleware(TrustedHostMiddleware, allowed_hosts=[h.strip() for h in allowed_hosts.split(",")])

    @api.middleware("http")
    async def workspace(request, call_next):
        provided = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if request.url.path.startswith("/api/") and token and not hmac.compare_digest(provided.encode(), token.encode()):
            return JSONResponse({"error": {"code": "unauthorized", "message": "A valid workspace bearer token is required."}}, status_code=401)
        origin = request.headers.get("Origin")
        if request.method not in ("GET", "HEAD", "OPTIONS") and origin and origin != f"{request.url.scheme}://{request.url.netloc}":
            return JSONResponse({"error": {"code": "cross_origin", "message": "Use the same-origin workbench."}}, status_code=403)
        identity = request.cookies.get(COOKIE, "")
        fresh = not TOKEN.fullmatch(identity)
        if fresh:
            identity = secrets.token_urlsafe(32)
        request.state.owner = hashlib.sha256(identity.encode()).hexdigest()
        response = await call_next(request)
        if fresh:
            response.set_cookie(COOKIE, identity, httponly=True, samesite="strict",
                                secure=request.url.scheme == "https", max_age=30 * 24 * 3600)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @api.exception_handler(Problem)
    async def problem_handler(request, exc):
        return JSONResponse({"error": exc.payload()}, status_code=exc.status)

    @api.exception_handler(RequestValidationError)
    async def validation_handler(request, exc):
        fields = [".".join(str(x) for x in e["loc"]) for e in exc.errors()][:8]
        return JSONResponse({"error": {"code": "invalid_request", "message": "Invalid request fields: " + ", ".join(fields)}}, status_code=422)

    @api.exception_handler(500)
    async def internal_error(request, exc):
        return JSONResponse({"error": {"code": "internal_error", "message": "The workbench could not complete this request."}}, status_code=500)

    @api.get("/", include_in_schema=False)
    def home():
        return FileResponse(STATIC / "index.html", headers={
            "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                       "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        })

    @api.get("/ui.js", include_in_schema=False)
    def script():
        return FileResponse(STATIC / "ui.js", media_type="text/javascript")

    @api.get("/health")
    def health():
        return {"status": "ok"}

    @api.get("/samples/{name}", include_in_schema=False)
    def sample(name: str):
        if name not in {"orders.csv", "products.csv"}:
            raise Problem("sample_not_found", "Sample not found.", 404)
        return FileResponse(SAMPLES / name, media_type="text/csv")

    @api.get("/api/runs")
    def list_runs(request: Request):
        return service.list_runs(request.state.owner)

    @api.post("/api/runs")
    async def upload(request: Request, idempotency_key: str | None = Header(default=None)):
        # Limit the ASGI stream, including chunked multipart input, before it
        # enters the spool. The service separately caps actual file bytes.
        max_body = MAX_BYTES + 256 * 1024
        try:
            declared = int(request.headers.get("content-length", "0"))
        except ValueError as exc:
            raise Problem("invalid_request", "Invalid Content-Length.") from exc
        if declared > max_body:
            raise Problem("upload_limit", "Combined upload exceeds 32 MiB.", 413)
        if not request.headers.get("content-type", "").lower().startswith("multipart/form-data;"):
            raise Problem("invalid_request", "Upload files using multipart/form-data.")
        received = 0

        async def receive():
            nonlocal received
            message = await request.receive()
            received += len(message.get("body", b""))
            if received > max_body:
                raise Problem("upload_limit", "Combined upload exceeds 32 MiB.", 413)
            return message

        bounded = Request(request.scope, receive)
        with TemporaryDirectory(prefix="retail-upload-") as tmp:
            async with bounded.form(max_files=MAX_FILES, max_fields=1, max_part_size=16 * 1024) as form:
                files = form.getlist("files")
                if not files or any(not isinstance(f, UploadFile) for f in files):
                    raise Problem("missing_inputs", "Choose one or more CSV files.")
                try:
                    metadata = json.loads(form.get("metadata", "{}"))
                    if not isinstance(metadata, dict) or set(metadata) - {f.filename for f in files}:
                        raise ValueError
                    for value in metadata.values():
                        if (not isinstance(value, dict) or set(value) - {"role", "mapping", "encoding"}
                            or any(k in value and not isinstance(value[k], str) for k in ("role", "encoding"))
                            or not isinstance(value.get("mapping", {}), dict)
                            or any(not isinstance(v, str) for v in value.get("mapping", {}).values())):
                            raise ValueError
                except (ValueError, TypeError) as exc:
                    raise Problem("invalid_metadata", "Metadata must map filenames to role, encoding and field mapping objects.") from exc
                inputs = []
                total = 0
                for i, file in enumerate(files):
                    path = Path(tmp) / str(i)
                    with path.open("wb") as target:
                        while chunk := await file.read(64 * 1024):
                            total += len(chunk)
                            if total > MAX_BYTES:
                                raise Problem("upload_limit", "Combined upload exceeds 32 MiB.", 413)
                            target.write(chunk)
                    opts = metadata.get(file.filename, {})
                    inputs.append(Input(path, file.filename or "", opts.get("role"), opts.get("mapping", {}),
                                        opts.get("encoding", "utf-8-sig")))
            return await run_in_threadpool(service.ingest, request.state.owner, inputs, idempotency_key)

    @api.get("/api/runs/{run_id}")
    def get_run(request: Request, run_id: str):
        return service.get_run(request.state.owner, run_id)

    @api.get("/api/runs/{run_id}/artifacts/{name}")
    def artifact(request: Request, run_id: str, name: str):
        return FileResponse(service.artifact(request.state.owner, run_id, name), filename=name,
                            media_type="application/octet-stream")

    @api.post("/api/runs/{run_id}/chat", openapi_extra={"requestBody": {
        "required": True, "content": {"application/json": {"schema": {
            "type": "object", "required": ["question"],
            "properties": {"question": {"type": "string", "maxLength": 1500},
                           "session_id": {"type": "string"}, "plan": {"type": "object"}},
        }}}
    }})
    async def chat(request: Request, run_id: str):
        if request.headers.get("Content-Type", "").lower().split(";")[0].strip() != "application/json":
            raise Problem("invalid_request", "Send chat requests as application/json.", 415)
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > 24 * 1024:
                raise Problem("request_limit", "Chat request exceeds 24 KiB.", 413)
        try:
            body = ChatRequest.model_validate_json(bytes(chunks))
        except ValueError as exc:
            raise Problem("invalid_request", "Chat request has invalid fields or plan.", 422) from exc
        return await run_in_threadpool(ask, service, request.state.owner, run_id, body.question,
                                       session_id=body.session_id, structured=body.plan)

    @api.get("/api/runs/{run_id}/sessions/{session_id}")
    def history(request: Request, run_id: str, session_id: str):
        return service.history(request.state.owner, run_id, session_id)

    return api


load_dotenv()
app = create_app()
