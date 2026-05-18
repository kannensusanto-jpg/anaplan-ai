let API_KEY           = "";
let JOB_SOURCE        = "anaplan";
let ACTIVE_FORM_ID    = "";
let SELECTED_EPM      = "";      // "anaplan" | "excel"
let EDIT_CONFIG_FORM  = "";      // form_id targeted by the Edit Config file input

const $ = id => document.getElementById(id);

function setStatus(id, msg, type = "") {
  const el = $(id);
  el.textContent = msg;
  el.className   = "status-msg " + type;
}

// ── Auth ──────────────────────────────────────────────────────────────────────

async function verifyKey() {
  API_KEY = $("api-key").value.trim();
  if (!API_KEY) { setStatus("auth-status", "Enter an API key", "error"); return; }

  const resp = await apiFetch("/v1/client/me");
  if (resp.ok) {
    const data = await resp.json();
    setStatus("auth-status", `Authenticated as ${data.company_name}`, "success");
    show("epm-section");
    await loadProfileOptions();
  } else {
    setStatus("auth-status", "Invalid API key", "error");
  }
}

// ── EPM Tool Selection ────────────────────────────────────────────────────────

async function selectEPM(tool) {
  SELECTED_EPM = tool;

  // Highlight selected card
  document.querySelectorAll(".epm-card").forEach(c => c.classList.remove("selected"));
  event.currentTarget.classList.add("selected");

  // Reset sections
  hide("forms-section");
  hide("anaplan-section");
  hide("upload-section");
  hide("add-form-panel");
  hide("add-form-anaplan");
  hide("add-form-excel");
  hide("form-template-btn");

  if (tool === "anaplan") {
    $("forms-sub").textContent = "Pick a registered Anaplan form to generate AI commentary.";
    show("form-template-btn");
    show("forms-section");
    show("anaplan-section");
    await loadAnaplanViews();
    await loadForms();
  } else if (tool === "excel") {
    $("forms-sub").textContent = "Pick a registered Excel form to generate AI commentary.";
    show("form-template-btn");
    show("forms-section");
    show("upload-section");
    await loadForms();
  }
}

// ── Form Picker ───────────────────────────────────────────────────────────────

async function loadForms() {
  const resp = await apiFetch("/v1/forms");
  if (!resp.ok) { setStatus("forms-status", "Could not load forms", "error"); return; }
  const all = await resp.json();
  const forms = all.filter(f =>
    SELECTED_EPM === "anaplan" ? f.form_source === "anaplan" : f.form_source === "excel"
  );
  renderFormList(forms);
}

function renderFormList(forms) {
  const el = $("form-list");
  if (!forms.length) {
    el.innerHTML = '<p class="empty-msg">No forms registered yet. Add one below.</p>';
    return;
  }
  el.innerHTML = forms.map(f => `
    <div class="form-card" id="fcard-${f.form_id}">
      <div class="form-card-info">
        <span class="form-name">${escHtml(f.form_name)}</span>
        <span class="badge badge-profile">${escHtml(f.profile_name)}</span>
      </div>
      <div class="form-card-actions">
        ${f.form_source === "anaplan"
          ? `<button class="btn-sm" onclick="generateFromAnaplanForm('${esc(f.form_id)}')">Generate</button>`
          : `<button class="btn-sm" onclick="openGridUpload('${esc(f.form_id)}', '${esc(f.form_name)}')">Upload &amp; Generate</button>`
        }
        <button class="btn-sm btn-outline" onclick="openEditConfig('${esc(f.form_id)}')">Edit Config</button>
        <button class="btn-sm btn-danger-sm" onclick="deleteForm('${esc(f.form_id)}')">Remove</button>
      </div>
    </div>
  `).join("");
}

async function deleteForm(formId) {
  if (!confirm("Remove this form config?")) return;
  const resp = await apiFetch(`/v1/forms/${encodeURIComponent(formId)}`, { method: "DELETE" });
  if (resp.ok) await loadForms();
  else setStatus("forms-status", "Delete failed", "error");
}

function openEditConfig(formId) {
  EDIT_CONFIG_FORM = formId;
  const input = $("edit-config-file");
  input.value = "";
  input.click();
}

async function submitEditConfig() {
  const file = $("edit-config-file").files[0];
  if (!file || !EDIT_CONFIG_FORM) return;

  setStatus("forms-status", `Updating config for form...`);

  const form = new FormData();
  form.append("file", file);

  const resp = await fetch(`/v1/forms/${encodeURIComponent(EDIT_CONFIG_FORM)}/config`, {
    method:  "POST",
    headers: { "X-API-Key": API_KEY },
    body:    form,
  });

  if (!resp.ok) {
    setStatus("forms-status", await errText(resp), "error");
    return;
  }

  setStatus("forms-status", "Config updated.", "success");
  await loadForms();
}

// ── Add Form panel ────────────────────────────────────────────────────────────

function toggleAddForm() {
  const panel = $("add-form-panel");
  const isHidden = panel.classList.contains("hidden");
  panel.classList.toggle("hidden");
  if (isHidden) {
    hide("add-form-anaplan");
    hide("add-form-excel");
    if (SELECTED_EPM === "anaplan") show("add-form-anaplan");
    else if (SELECTED_EPM === "excel") show("add-form-excel");
  }
}

async function loadAnaplanViews() {
  const resp = await apiFetch("/v1/anaplan/views");
  if (!resp.ok) return;
  const { views } = await resp.json();
  const sel = $("anaplan-views-select");
  sel.innerHTML = '<option value="">— select a view —</option>' +
    views.map(v => `<option value="${esc(v.id)}" data-name="${esc(v.name)}">${escHtml(v.name)}</option>`).join("");
}

async function loadProfileOptions() {
  const resp = await apiFetch("/v1/profiles");
  if (!resp.ok) return;
  const profiles = await resp.json();
  const sel = $("anaplan-profile-select");
  sel.innerHTML = profiles
    .map(p => `<option value="${esc(p.profile_name)}">${escHtml(p.profile_name)}</option>`)
    .join("");
}

async function registerAnaplanView() {
  const sel      = $("anaplan-views-select");
  const viewId   = sel.value;
  const viewName = sel.options[sel.selectedIndex]?.dataset.name || viewId;
  const profile  = $("anaplan-profile-select").value;

  if (!viewId) { setStatus("add-form-status", "Select a view first", "error"); return; }

  setStatus("add-form-status", "Registering...");
  const resp = await apiFetch("/v1/forms", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      form_id:      viewId,
      form_name:    viewName,
      form_source:  "anaplan",
      profile_name: profile,
      view_id:      viewId,
    }),
  });

  if (resp.ok) {
    setStatus("add-form-status", `Registered: ${viewName}`, "success");
    await loadForms();
  } else {
    setStatus("add-form-status", await errText(resp), "error");
  }
}

async function uploadFormConfig() {
  const file = $("form-config-file").files[0];
  if (!file) return;
  setStatus("form-config-status", "Parsing form config...");
  setStatus("form-config-status",
    "Use the API directly to register a form config, or download and fill in the Form Config Template above.",
    "error");
}

// ── Anaplan-source form generation ────────────────────────────────────────────

async function generateFromAnaplanForm(formId) {
  ACTIVE_FORM_ID = formId;
  JOB_SOURCE     = "anaplan-form";
  setStatus("forms-status", "Reading from Anaplan and generating commentary...");

  const resp = await apiFetch("/v1/anaplan/generate-form", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ form_id: formId }),
  });

  if (!resp.ok) {
    setStatus("forms-status", await errText(resp), "error");
    return;
  }

  const data = await resp.json();
  setStatus("forms-status",
    `Generated ${data.generated} rows · skipped ${data.skipped}`, "success");
  await loadPreview();
}

// ── Excel grid upload (for Excel-source forms) ────────────────────────────────

function openGridUpload(formId, formName) {
  ACTIVE_FORM_ID = formId;
  $("grid-form-name").textContent = formName;
  show("grid-upload-section");
  hide("forms-section");
  $("grid-file").value = "";
  setStatus("grid-status", "");
}

function cancelGridUpload() {
  hide("grid-upload-section");
  show("forms-section");
}

async function uploadGrid() {
  const file = $("grid-file").files[0];
  if (!file) return;
  setStatus("grid-status", `Uploading ${file.name}...`);

  const form = new FormData();
  form.append("file", file);
  form.append("form_id", ACTIVE_FORM_ID);

  const resp = await fetch("/v1/upload/grid-generate", {
    method:  "POST",
    headers: { "X-API-Key": API_KEY },
    body:    form,
  });

  if (!resp.ok) { setStatus("grid-status", await errText(resp), "error"); return; }

  const data = await resp.json();
  setStatus("grid-status",
    `Generated ${data.generated} rows · skipped ${data.skipped}`, "success");
  JOB_SOURCE = "grid";
  hide("grid-upload-section");
  show("forms-section");
  await loadPreview();
}

// ── Quick Generate (Anaplan module — legacy) ──────────────────────────────────

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

// ── Flat Template Upload (Excel — no form registration needed) ────────────────

async function uploadFile() {
  const file = $("excel-file").files[0];
  if (!file) return;
  setStatus("upload-status", `Uploading ${file.name}...`);

  const form = new FormData();
  form.append("file", file);

  const resp = await fetch("/v1/upload/generate", {
    method:  "POST",
    headers: { "X-API-Key": API_KEY },
    body:    form,
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
  const resp = await apiFetch("/v1/jobs/preview");
  if (!resp.ok) return;
  const preview = await resp.json();
  renderPreview(preview);
  show("preview-section");
  $("preview-section").scrollIntoView({ behavior: "smooth", block: "start" });
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
    cols.forEach(c => {
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
    html += `<tr><td colspan="${cols.length}" class="skipped-hdr"><strong>Skipped</strong></td></tr>`;
    skipped.forEach(s => {
      html += `<tr class="skipped-row"><td>${escHtml(s.account || "")}</td>`;
      html += `<td>${escHtml(s.cost_center || "")}</td><td>${escHtml(s.time_period || "")}</td>`;
      html += `<td colspan="${cols.length - 3}" class="skipped">${escHtml(s.reason || "")}</td></tr>`;
    });
  }

  html += "</tbody></table>";
  $("preview-table-wrap").innerHTML = html;
}

// ── Preview actions ───────────────────────────────────────────────────────────

async function exportPreview() {
  const resp = await apiFetch("/v1/jobs/preview/export");
  if (!resp.ok) return;
  _download(await resp.blob(), "commentary_preview.xlsx");
}

async function rejectPreview() {
  const resp = await apiFetch("/v1/jobs/reject", { method: "POST" });
  if (resp.ok) {
    hide("preview-section");
    setStatus("generate-status", "Preview discarded.");
    setStatus("upload-status",   "Preview discarded.");
    setStatus("forms-status",    "Preview discarded.");
  }
}

async function approvePreview() {
  setStatus("approve-status", "Approving...");

  if (JOB_SOURCE === "upload") {
    const file = $("excel-file").files[0];
    if (!file) {
      setStatus("approve-status",
        "Re-select your original file to download the annotated version.", "error");
      return;
    }
    const form = new FormData();
    form.append("file", file);
    const resp = await fetch("/v1/upload/approve-download", {
      method:  "POST",
      headers: { "X-API-Key": API_KEY },
      body:    form,
    });
    if (!resp.ok) { setStatus("approve-status", await errText(resp), "error"); return; }
    _download(await resp.blob(), "commentary_output.xlsx");
    hide("preview-section");
    return;
  }

  if (JOB_SOURCE === "grid" || JOB_SOURCE === "anaplan-form") {
    const resp = await apiFetch("/v1/forms/approve", { method: "POST" });
    if (!resp.ok) { setStatus("approve-status", await errText(resp), "error"); return; }
    hide("preview-section");
    setStatus("forms-status", "Commentary written to Anaplan.", "success");
    await loadForms();
    return;
  }

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
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function esc(str) {
  return String(str).replace(/'/g, "\\'").replace(/"/g, "&quot;");
}

function show(id) { $(id).classList.remove("hidden"); }
function hide(id) { $(id).classList.add("hidden"); }

function _download(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a   = document.createElement("a");
  a.href    = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
