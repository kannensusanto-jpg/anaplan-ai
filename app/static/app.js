let API_KEY    = "";
let JOB_SOURCE = "anaplan"; // "anaplan" | "upload"

const $ = id => document.getElementById(id);

function setStatus(id, msg, type = "") {
  const el = $(id);
  el.textContent = msg;
  el.className   = "status-msg " + type;
}

// ── Auth ─────────────────────────────────────────────────────────────────────

async function verifyKey() {
  API_KEY = $("api-key").value.trim();
  if (!API_KEY) { setStatus("auth-status", "Enter an API key", "error"); return; }

  const resp = await apiFetch("/v1/client/me");
  if (resp.ok) {
    const data = await resp.json();
    setStatus("auth-status", `Authenticated as ${data.company_name}`, "success");
    show("anaplan-section");
    show("upload-section");
  } else {
    setStatus("auth-status", "Invalid API key", "error");
  }
}

// ── Anaplan generate ─────────────────────────────────────────────────────────

async function triggerGenerate() {
  setStatus("generate-status", "Queuing job...");
  const resp = await apiFetch("/v1/jobs/generate", { method: "POST" });
  if (!resp.ok) { setStatus("generate-status", await errText(resp), "error"); return; }

  const { job_id } = await resp.json();
  setStatus("generate-status", `Job queued (${job_id}) — polling...`);
  JOB_SOURCE = "anaplan";
  pollJob(job_id);
}

async function pollJob(job_id) {
  const interval = setInterval(async () => {
    const resp = await apiFetch(`/v1/jobs/status/${job_id}`);
    if (!resp.ok) return;
    const data = await resp.json();
    setStatus("generate-status", `Status: ${data.status}`);

    if (data.status === "complete" || data.result?.status === "pending_review") {
      clearInterval(interval);
      setStatus("generate-status", "Generation complete — loading preview...", "success");
      await loadPreview();
    } else if (data.status === "failed") {
      clearInterval(interval);
      setStatus("generate-status", "Job failed. Check logs.", "error");
    }
  }, 3000);
}

// ── Excel upload ─────────────────────────────────────────────────────────────

async function uploadFile() {
  const file = $("excel-file").files[0];
  if (!file) return;
  setStatus("upload-status", `Uploading ${file.name}...`);

  const form = new FormData();
  form.append("file", file);

  const resp = await fetch("/v1/upload/generate", {
    method: "POST",
    headers: { "X-API-Key": API_KEY },
    body: form,
  });

  if (!resp.ok) { setStatus("upload-status", await errText(resp), "error"); return; }

  const data = await resp.json();
  setStatus("upload-status",
    `Generated ${data.generated} rows · skipped ${data.skipped}`, "success");
  JOB_SOURCE = "upload";
  await loadPreview();
}

// ── Preview ───────────────────────────────────────────────────────────────────

async function loadPreview() {
  const endpoint = JOB_SOURCE === "anaplan" ? "/v1/jobs/preview" : "/v1/upload/preview/export";

  // For Anaplan, we get JSON. For upload the export endpoint returns Excel binary.
  // Both sources share the same Redis key, so just use /v1/jobs/preview for JSON.
  const resp = await apiFetch("/v1/jobs/preview");
  if (!resp.ok) { return; }

  const preview = await resp.json();
  renderPreview(preview);
  show("preview-section");
}

function renderPreview(preview) {
  const rows    = preview.rows    || [];
  const skipped = preview.skipped || [];

  $("preview-summary").textContent =
    `${rows.length} rows generated · ${skipped.length} skipped`;

  const cols    = ["account", "cost_center", "time_period", "actual", "budget",
                   "variance_dollars", "variance_pct", "commentary"];
  const headers = ["Account", "Cost Center", "Period", "Actual", "Budget",
                   "Var $", "Var %", "AI Commentary"];

  let html = "<table><thead><tr>";
  headers.forEach(h => { html += `<th>${h}</th>`; });
  html += "</tr></thead><tbody>";

  rows.forEach(r => {
    html += "<tr>";
    cols.forEach((c, i) => {
      let val = r[c] ?? "";
      if (c === "variance_pct") val = (val * 100).toFixed(1) + "%";
      if (c === "actual" || c === "budget" || c === "variance_dollars")
        val = Number(val).toLocaleString();
      const cls = c === "commentary" ? " class='commentary'" : "";
      html += `<td${cls}>${escHtml(String(val))}</td>`;
    });
    html += "</tr>";
  });

  if (skipped.length) {
    html += `<tr><td colspan="${cols.length}" class="skipped"><strong>Skipped (below materiality or favorable)</strong></td></tr>`;
    skipped.forEach(s => {
      html += `<tr class="skipped-row"><td>${escHtml(s.account)}</td>`;
      html += `<td>${escHtml(s.cost_center)}</td><td>${escHtml(s.time_period)}</td>`;
      html += `<td colspan="${cols.length - 3}" class="skipped">${escHtml(s.reason)}</td></tr>`;
    });
  }

  html += "</tbody></table>";
  $("preview-table-wrap").innerHTML = html;
}

// ── Actions ───────────────────────────────────────────────────────────────────

async function exportPreview() {
  window.location = JOB_SOURCE === "anaplan"
    ? "/v1/jobs/preview/export"
    : "/v1/upload/preview/export";
  // browser will prompt download — headers carry API key via URL trick not possible,
  // so open a fetch + blob download instead
  const resp = await apiFetch(
    JOB_SOURCE === "anaplan" ? "/v1/jobs/preview/export" : "/v1/upload/preview/export"
  );
  if (!resp.ok) return;
  const blob = await resp.blob();
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = "commentary_preview.xlsx";
  a.click();
  URL.revokeObjectURL(url);
}

async function rejectPreview() {
  const resp = await apiFetch("/v1/jobs/reject", { method: "POST" });
  if (resp.ok) {
    hide("preview-section");
    setStatus("generate-status", "Preview discarded.");
    setStatus("upload-status", "Preview discarded.");
  }
}

async function approvePreview() {
  setStatus("approve-status", "Approving...");

  if (JOB_SOURCE === "upload") {
    // For upload, user must re-upload original to receive annotated file
    const file = $("excel-file").files[0];
    if (!file) {
      setStatus("approve-status", "Re-select your original file to download the annotated version.", "error");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch("/v1/upload/approve-download", {
      method: "POST",
      headers: { "X-API-Key": API_KEY },
      body: form,
    });
    if (!resp.ok) { setStatus("approve-status", await errText(resp), "error"); return; }
    const blob = await resp.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = "commentary_output.xlsx";
    a.click();
    URL.revokeObjectURL(url);
    hide("preview-section");
    setStatus("approve-status", "Downloaded.", "success");
    return;
  }

  // Anaplan path: queue write job
  const resp = await apiFetch("/v1/jobs/approve", { method: "POST" });
  if (!resp.ok) { setStatus("approve-status", await errText(resp), "error"); return; }
  const { job_id } = await resp.json();
  setStatus("approve-status", `Write job queued (${job_id}) — polling...`);

  const interval = setInterval(async () => {
    const r = await apiFetch(`/v1/jobs/status/${job_id}`);
    if (!r.ok) return;
    const d = await r.json();
    if (d.status === "complete" || d.result?.status === "written") {
      clearInterval(interval);
      hide("preview-section");
      setStatus("generate-status", "Commentary written to Anaplan.", "success");
    } else if (d.status === "failed") {
      clearInterval(interval);
      setStatus("approve-status", "Write failed. Check logs.", "error");
    }
  }, 3000);
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function apiFetch(path, opts = {}) {
  return fetch(path, {
    ...opts,
    headers: { "X-API-Key": API_KEY, ...(opts.headers || {}) },
  });
}

async function errText(resp) {
  try { const d = await resp.json(); return d.detail || resp.statusText; }
  catch { return resp.statusText; }
}

function escHtml(str) {
  return str.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function show(id) { $(id).classList.remove("hidden"); }
function hide(id) { $(id).classList.add("hidden"); }
