"use strict";

const get = (id) => document.getElementById(id);
const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
};

let runId = null;
let sessionId = null;
let version = null;
let accessToken = "";
let working = false;

async function request(path, options = {}) {
    const headers = new Headers(options.headers);
    if (accessToken) headers.set("Authorization", "Bearer " + accessToken);
    const response = await fetch(path, {...options, headers});
    if (response.ok && options.download) return response.blob();
    const body = await response.json().catch(() => null);
    if (!response.ok) {
        if (response.status === 401) get("access").hidden = false;
        throw new Error(body?.error?.message || body?.detail || "Request failed (" + response.status + ").");
    }
    return body;
}

function status(id, text, error = false) {
    get(id).textContent = text;
    get(id).classList.toggle("error", error);
}

function controls() {
    for (const id of ["clean", "sample", "runs"]) get(id).disabled = working;
    for (const id of ["ask", "new-chat"]) get(id).disabled = working || !version;
}

function details(title, body) {
    const box = element("details");
    box.append(element("summary", title), element("pre", JSON.stringify(body, null, 2)));
    return box;
}

async function download(path, filename) {
    try {
        const blob = await request(path, {download: true});
        const link = element("a");
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        link.click();
        setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    } catch (error) {
        status("upload-status", error.message, true);
    }
}

function renderRun(run) {
    const area = get("datasets");
    area.replaceChildren();
    version = null;
    get("chat-help").textContent = "Load a cleaned run to start. Follow-ups can reuse the previous turn’s filters.";
    if (!run) return;
    if (run.status !== "succeeded") {
        area.append(element("p", run.error?.message || "Run is " + run.status + ".", run.error ? "error" : "muted"));
        return;
    }
    version = run.version;
    get("chat-help").textContent = "Questions use this clean version. Try “Only stores in the West region,” then ask about return rates.";
    area.append(element("p", "Clean version " + version.slice(0, 12), "muted"));
    for (const data of run.datasets) {
        const node = element("details");
        node.append(element("summary", data.name + " · " + data.profile_after.row_count + " rows"));
        node.append(element("p", data.role + " · " + data.issues.length + " issue types", "muted"));
        node.append(details("Profile before", data.profile_before));
        node.append(details("Cleaning plan and unresolved issues", {steps: data.cleaning_plan, issues: data.issues}));
        node.append(details("Profile after and validation", {profile: data.profile_after, validation: data.validation}));
        const actions = element("div", undefined, "actions");
        for (const [kind, file] of Object.entries(data.artifacts)) {
            const button = element("button", "Download " + kind, "secondary");
            button.addEventListener("click", () => download("/api/runs/" + run.run_id + "/artifacts/" + file, file));
            actions.append(button);
        }
        node.append(actions);
        area.append(node);
    }
}

function table(preview) {
    const wrapper = element("div", undefined, "table-scroll");
    const grid = element("table");
    grid.setAttribute("aria-label", "Executed result preview");
    const head = grid.createTHead().insertRow();
    const cols = Object.keys(preview[0]);
    for (const column of cols) {
        const cell = element("th", column);
        cell.scope = "col";
        head.append(cell);
    }
    const body = grid.createTBody();
    for (const record of preview) {
        const row = body.insertRow();
        for (const column of cols) row.insertCell().textContent = record[column] ?? "—";
    }
    wrapper.append(grid);
    return wrapper;
}

function renderTurn(turn) {
    const item = element("article", undefined, "turn");
    item.append(element("p", turn.question, "question"),
        element("p", turn.answer.summary, "answer"));
    if (turn.fallback_reason) item.append(element("p", "Used offline fallback · " + turn.fallback_reason, "muted"));
    if (turn.answer.preview.length) item.append(table(turn.answer.preview));
    if (turn.trace) {
        const trace = turn.trace;
        const panel = element("details");
        panel.append(element("summary", "Execution evidence"));
        const overview = element("dl", undefined, "evidence");
        const facts = {
            "Dataset": trace.dataset_name + " · " + trace.dataset_version.slice(0, 12),
            "Rows considered": trace.row_count_considered,
            "Filters": trace.filters.map(f => f.field + " " + f.op + " " + JSON.stringify(f.value)).join(", ") || "All rows",
            "Joins": trace.joins.map(j => j.cardinality.replaceAll("_", " ") + " · " + j.left_key + " → " + j.right_key + " · " + j.scoped_unmatched_rows + " unmatched in scope").join(", ") || "None",
            "Operations": trace.operations.join(" → ") || "Scope updated"
        };
        for (const [label, value] of Object.entries(facts)) {
            overview.append(element("dt", label), element("dd", value));
        }
        panel.append(overview, details("Full execution trace", trace));
        item.append(panel);
    }
    item.append(details("Query plan and execution status", {plan: turn.plan, status: turn.status, planner: turn.planner}));
    get("turns").append(item);
    return item;
}

async function selectRun(id) {
    runId = id || null;
    sessionId = null;
    get("turns").replaceChildren();
    const run = runId ? await request("/api/runs/" + runId) : null;
    renderRun(run);
    if (!version) return;
    const remembered = localStorage.getItem("retail-session:" + runId);
    if (remembered) {
        try {
            const history = await request("/api/runs/" + runId + "/sessions/" + remembered);
            sessionId = remembered;
            for (const turn of history) renderTurn(turn);
        } catch {
            localStorage.removeItem("retail-session:" + runId);
        }
    }
}

async function refreshRuns(selected) {
    const runs = await request("/api/runs");
    get("access").hidden = true;
    get("runs").replaceChildren(new Option("Choose a run", ""));
    for (const run of runs) get("runs").append(new Option(run.run_id.slice(0, 10) + " · " + run.status, run.run_id));
    const value = selected || localStorage.getItem("retail-run");
    if (runs.some((run) => run.run_id === value)) {
        get("runs").value = value;
        await selectRun(value);
    }
}

async function clean(form) {
    working = true;
    controls();
    status("upload-status", "Profiling, cleaning and validating…");
    try {
        const run = await request("/api/runs", {method: "POST", body: form, headers: {"Idempotency-Key": crypto.randomUUID()}});
        localStorage.setItem("retail-run", run.run_id);
        await refreshRuns(run.run_id);
        status("upload-status", run.status === "succeeded" ? "Cleaned artifacts are ready." : run.error?.message || run.status, run.status === "failed");
    } catch (error) {
        status("upload-status", error.message, true);
    } finally {
        working = false;
        controls();
    }
}

get("unlock").addEventListener("click", async () => {
    accessToken = get("access-token").value;
    get("access-token").value = "";
    try { await refreshRuns(); status("upload-status", "Connected."); }
    catch (error) { status("upload-status", error.message, true); }
    controls();
});

get("runs").addEventListener("change", async () => {
    working = true;
    controls();
    try {
        localStorage.setItem("retail-run", get("runs").value);
        await selectRun(get("runs").value);
        status("chat-status", "");
    } catch (error) { status("upload-status", error.message, true); }
    finally { working = false; controls(); }
});

get("upload").addEventListener("submit", (event) => {
    event.preventDefault();
    const data = new FormData();
    for (const file of get("files").files) data.append("files", file);
    if (!data.has("files")) return status("upload-status", "Choose at least one CSV.", true);
    if (get("metadata").value.trim()) data.set("metadata", get("metadata").value.trim());
    clean(data);
});

get("sample").addEventListener("click", async () => {
    try {
        const data = new FormData();
        for (const filename of ["orders.csv", "products.csv"]) {
            data.append("files", await request("/samples/" + filename, {download: true}), filename);
        }
        await clean(data);
    } catch (error) { status("upload-status", error.message, true); }
});

get("new-chat").addEventListener("click", () => {
    sessionId = null;
    localStorage.removeItem("retail-session:" + runId);
    get("turns").replaceChildren();
    status("chat-status", "New conversation.");
    get("question").focus();
});

get("chat").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!version || working) return;
    const question = get("question").value.trim();
    if (!question) return;
    working = true;
    controls();
    status("chat-status", "Planning and checking the answer…");
    try {
        const turn = await request("/api/runs/" + runId + "/chat", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({question, session_id: sessionId})
        });
        sessionId = turn.session_id;
        localStorage.setItem("retail-session:" + runId, sessionId);
        get("question").value = "";
        const item = renderTurn(turn);
        item.scrollIntoView({block: "nearest"});
        status("chat-status", "Answer ready.");
    } catch (error) { status("chat-status", error.message, true); }
    finally { working = false; controls(); }
});

refreshRuns().catch((error) => status("upload-status", error.message, true)).finally(controls);
