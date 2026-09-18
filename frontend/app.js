const API_BASE = "http://localhost:8080";

// A phone number that genuinely exists on a planted ring member in the local
// synthetic dataset (data/ground_truth_rings.csv + data/claims.csv, ring-0000)
// - submitting a new claim with it should get FLAGGED by the real trained
// model, not by anything faked in this frontend.
const RING_DEMO_PHONE = "+917552228129";

const SCORING_API_BASE = "http://localhost:8000";

// All mutable UI state lives here instead of scattered globals, so render()
// functions have one obvious place to read from.
const state = {
  token: null,
  role: null,
  username: null,
  sessionClaims: [], // [{id, claimantName, claimantPhone, status}], most recent first
  activeClaimId: null,
  pollHandle: null,
};

const $ = (id) => document.getElementById(id);

// --- Theme -------------------------------------------------------------

// Reflects the current <html data-theme> (set synchronously by the inline script
// in index.html's <head>, before first paint) onto the toggle button's icon.
function syncThemeButton() {
  const isDark = document.documentElement.dataset.theme === "dark";
  $("theme-toggle").textContent = isDark ? "☀️" : "🌙";
  $("theme-toggle").title = isDark ? "Switch to light theme" : "Switch to dark theme";
}

// Flips light/dark, remembers the choice in localStorage (per-browser only, never
// sent anywhere - see the head script for why the default is light, not OS-driven).
function toggleTheme() {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try {
    localStorage.setItem("claimguard-theme", next);
  } catch {
    // Private browsing / blocked storage - the choice just won't survive a reload.
  }
  syncThemeButton();
}

syncThemeButton();
$("theme-toggle").addEventListener("click", toggleTheme);

// Wraps fetch with the JWT header (when present) and turns a non-2xx
// response into a thrown Error carrying the backend's RFC 7807 detail text,
// so every caller can just try/catch instead of checking response.ok itself.
async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const problem = await res.json();
      detail = problem.detail || problem.title || detail;
    } catch { /* body wasn't JSON */ }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

// Logs in against POST /api/auth/login, stores the JWT + role in memory
// (deliberately not localStorage - this is a demo token, no reason to
// outlive the tab), and swaps the login screen for the app shell.
async function login(username, password) {
  const data = await api("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  state.token = data.token;
  state.role = data.role;
  state.username = username;
  $("session-user").textContent = `${username} · ${data.role}`;
  $("session-info").classList.remove("hidden");
  $("login-view").classList.add("hidden");
  $("app-view").classList.remove("hidden");
  $("incidentDate").value = new Date().toISOString().slice(0, 10);
}

// Clears all in-memory session state and returns to the login screen.
// Nothing server-side to call - JWTs are stateless, there's no session to revoke.
function logout() {
  stopPolling();
  Object.assign(state, { token: null, role: null, username: null, sessionClaims: [], activeClaimId: null });
  $("session-info").classList.add("hidden");
  $("app-view").classList.add("hidden");
  $("login-view").classList.remove("hidden");
  $("claim-detail").classList.add("hidden");
  $("empty-state").classList.remove("hidden");
  $("session-claims-list").innerHTML = "";
}

// Submits POST /api/claims with the intake form's current values, adds the
// new claim to the session list, and makes it the active claim.
async function submitClaim(formValues) {
  const claim = await api("/api/claims", { method: "POST", body: JSON.stringify(formValues) });
  state.sessionClaims.unshift(claim);
  renderSessionList();
  await selectClaim(claim.id);
}

// Fetches a claim's full detail (claim record + audit trail) and renders
// the detail panel. Called on selection and on every poll tick.
async function loadClaimDetail(claimId) {
  const [claim, auditEvents] = await Promise.all([
    api(`/api/claims/${claimId}`),
    api(`/api/claims/${claimId}/audit`),
  ]);
  renderClaimDetail(claim, auditEvents);
  return claim;
}

// Makes a claim the active one in the detail panel, loads its detail, and
// starts polling if it's still awaiting a fraud-score verdict.
async function selectClaim(claimId) {
  stopPolling();
  state.activeClaimId = claimId;
  renderSessionList();
  const claim = await loadClaimDetail(claimId);
  if (claim.status === "SUBMITTED") startPolling(claimId);
}

// Polls GET /api/claims/{id} every 2s while it's still SUBMITTED, mirroring
// how long the async outbox -> Kafka -> scoring -> Kafka pipeline actually
// takes to land a verdict. Stops itself the moment the status changes, or
// after 30 attempts (~60s) as a safety bound - if the scoring consumer
// process isn't running, this would otherwise poll forever.
function startPolling(claimId) {
  $("polling-note").classList.remove("hidden");
  let attempts = 0;
  state.pollHandle = setInterval(async () => {
    attempts += 1;
    try {
      const claim = await loadClaimDetail(claimId);
      if (claim.status !== "SUBMITTED" || attempts >= 30) stopPolling();
    } catch {
      stopPolling();
    }
  }, 2000);
}

function stopPolling() {
  if (state.pollHandle) clearInterval(state.pollHandle);
  state.pollHandle = null;
  $("polling-note").classList.add("hidden");
}

// Calls POST /api/claims/{id}/transitions and refreshes the detail panel
// with the result - the panel's own next render recomputes which actions
// are legal from the claim's new status.
async function performTransition(claimId, toStatus, reason) {
  const body = { toStatus };
  if (reason) body.reason = reason;
  await api(`/api/claims/${claimId}/transitions`, { method: "POST", body: JSON.stringify(body) });
  await loadClaimDetail(claimId);
}

// Calls GET /audit/verify and shows the hash-chain result inline next to
// the "Verify hash chain" button, rather than just trusting the trail looks right.
async function verifyChain(claimId) {
  const result = await api(`/api/claims/${claimId}/audit/verify`);
  const el = $("verify-result");
  el.textContent = result.valid ? `Valid (${result.events} events)` : "TAMPERED — chain broken";
  el.className = `verify-result ${result.valid ? "valid" : "invalid"}`;
}

// --- Rendering -------------------------------------------------------

const STATUS_LABELS = {
  SUBMITTED: "Submitted",
  UNDER_REVIEW: "Under review",
  FLAGGED: "Flagged",
  APPROVED: "Approved",
  DENIED: "Denied",
};

// A client-side mirror of backend/.../workflow/ClaimTransitions.java, used
// only to decide which action buttons to show - the backend is the actual
// authority and re-checks every one of these on the real request.
const TRANSITIONS = {
  SUBMITTED: { UNDER_REVIEW: ["ADJUSTER"] },
  UNDER_REVIEW: { FLAGGED: ["ADJUSTER"], APPROVED: ["ADJUSTER"], DENIED: ["ADJUSTER"] },
  FLAGGED: { UNDER_REVIEW: ["INVESTIGATOR"], DENIED: ["INVESTIGATOR"], APPROVED: ["INVESTIGATOR"] },
};
const REQUIRES_REASON = new Set(["FLAGGED->APPROVED"]);

function formatMoney(amount) {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(amount);
}

function formatDateTime(iso) {
  return new Date(iso).toLocaleString();
}

// Redraws the session-claims sidebar list, highlighting whichever claim is active.
function renderSessionList() {
  const list = $("session-claims-list");
  list.innerHTML = "";
  for (const claim of state.sessionClaims) {
    const li = document.createElement("li");
    li.className = claim.id === state.activeClaimId ? "active" : "";
    li.innerHTML = `<span class="claim-row-name">${claim.claimantName}</span><span class="claim-row-phone">${claim.claimantPhone}</span>`;
    li.addEventListener("click", () => selectClaim(claim.id));
    list.appendChild(li);
  }
}

// Redraws the whole detail panel (header, fields, status badge, action
// buttons, audit timeline) for one claim + its audit trail.
function renderClaimDetail(claim, auditEvents) {
  $("empty-state").classList.add("hidden");
  $("claim-detail").classList.remove("hidden");

  $("detail-claimant").textContent = claim.claimantName;
  $("detail-policy").textContent = claim.policyNumber;
  $("detail-amount").textContent = formatMoney(claim.claimAmount);
  $("detail-date").textContent = claim.incidentDate;
  $("detail-phone").textContent = claim.claimantPhone;
  $("detail-address").textContent = claim.claimantAddress;
  $("detail-shop").textContent = claim.repairShopName;
  $("detail-id").textContent = claim.id;

  const badge = $("status-badge");
  badge.textContent = STATUS_LABELS[claim.status] || claim.status;
  badge.className = `status-badge status-${claim.status}`;

  $("verify-result").textContent = "";
  $("verify-result").className = "verify-result";

  renderActions(claim);
  renderAuditTimeline(auditEvents);
  resetNarrative();

  // Keep the session-list copy of this claim's status in sync so the
  // sidebar reflects a flag that just arrived via polling.
  const cached = state.sessionClaims.find((c) => c.id === claim.id);
  if (cached) cached.status = claim.status;
}

// Builds the workflow action buttons legal for the CURRENT user's role
// from this claim's current status, per the TRANSITIONS map above.
function renderActions(claim) {
  const container = $("actions-buttons");
  container.innerHTML = "";
  $("reason-field").classList.add("hidden");
  $("action-error").classList.add("hidden");

  const legalTargets = TRANSITIONS[claim.status] || {};
  const allowedForRole = Object.entries(legalTargets).filter(([, roles]) => roles.includes(state.role));

  if (allowedForRole.length === 0) {
    container.innerHTML = `<span class="no-actions">No actions available for ${state.role} on a ${STATUS_LABELS[claim.status] || claim.status} claim.</span>`;
    return;
  }

  for (const [toStatus] of allowedForRole) {
    const btn = document.createElement("button");
    btn.textContent = `Move to ${STATUS_LABELS[toStatus] || toStatus}`;
    btn.addEventListener("click", () => handleActionClick(claim, toStatus));
    container.appendChild(btn);
  }
}

async function handleActionClick(claim, toStatus) {
  const needsReason = REQUIRES_REASON.has(`${claim.status}->${toStatus}`);
  const reasonInput = $("reason-input");
  if (needsReason) {
    $("reason-field").classList.remove("hidden");
    if (!reasonInput.value.trim()) {
      reasonInput.focus();
      return;
    }
  }
  $("action-error").classList.add("hidden");
  try {
    await performTransition(claim.id, toStatus, needsReason ? reasonInput.value.trim() : null);
    reasonInput.value = "";
  } catch (err) {
    $("action-error").textContent = err.message;
    $("action-error").classList.remove("hidden");
  }
}

// Renders the audit trail as a vertical timeline, oldest first (matching
// what GET /audit already returns), each entry showing who/what/when plus
// a truncated hash so the chain linkage is visible without overwhelming the UI.
// A FRAUD_SCORED event also gets its real SHAP feature contributions rendered
// as signed bars - parsed straight out of explanationJson, the same hash-chained
// field the audit log itself is built from, not a value invented by this page.
function renderAuditTimeline(events) {
  const list = $("audit-timeline");
  list.innerHTML = "";
  for (const event of events) {
    const li = document.createElement("li");
    let title;
    if (event.eventType === "FRAUD_SCORED") {
      title = `Fraud scored: ${Number(event.fraudScore).toFixed(4)} (ring ${event.ringId || "—"})`;
    } else if (event.eventType === "NARRATIVE_GENERATED") {
      // No " → status" suffix here on purpose - unlike every other event type, this one
      // never moves the claim (see ClaimService.recordNarrative), so fromStatus/toStatus
      // are always identical and showing them would read as a transition that didn't happen.
      title = "Investigator narrative generated";
    } else {
      title = `${event.eventType.replaceAll("_", " ")}${event.toStatus ? ` → ${STATUS_LABELS[event.toStatus] || event.toStatus}` : ""}`;
    }
    li.innerHTML = `
      <div class="audit-event-title">${title}</div>
      <div class="audit-event-meta">${event.actorRole} (${event.actorId}) · ${formatDateTime(event.occurredAt)}${event.reason ? ` · "${event.reason}"` : ""}</div>
      ${event.eventType === "FRAUD_SCORED" ? renderShapSection(event.explanationJson) : ""}
      ${event.eventType === "NARRATIVE_GENERATED" ? renderNarrativeAuditSection(event.explanationJson, event.modelVersion) : ""}
      <div class="audit-event-hash" title="${event.hash}">hash ${event.hash.slice(0, 16)}&hellip;</div>
    `;
    list.appendChild(li);
  }
}

// Parses one NARRATIVE_GENERATED event's explanationJson ({narrative, grounded} - see
// ClaimService.recordNarrative) and renders it inline in the audit timeline, so the
// permanent record of what an investigator read is visible right where it was recorded,
// not only in the claim detail panel's transient "Generate" result above.
function renderNarrativeAuditSection(explanationJsonText, modelVersion) {
  if (!explanationJsonText) return "";
  let explanation;
  try {
    explanation = JSON.parse(explanationJsonText);
  } catch {
    return "";
  }
  if (!explanation.narrative) return "";
  const badgeClass = explanation.grounded && (modelVersion || "").startsWith("ollama:")
    ? "badge-model" : "badge-fallback";
  return `
    <div class="shap-section">
      <div class="shap-title">Narrative shown to the investigator</div>
      <p style="margin:0 0 8px;font-size:13px;line-height:1.5">${explanation.narrative}</p>
      <span class="narrative-badge ${badgeClass}">${modelVersion || "unknown model"}</span>
    </div>`;
}

// Parses one FRAUD_SCORED event's explanationJson and renders its FEATURE_CONTRIBUTION
// evidence (real per-prediction SHAP values from the Tier 1 model - see
// app/model.py:score_claim) as a small signed bar chart: bars extending right in red
// pushed the score toward fraud, bars extending left in teal pushed it toward clean.
function renderShapSection(explanationJsonText) {
  if (!explanationJsonText) return "";
  let explanation;
  try {
    explanation = JSON.parse(explanationJsonText);
  } catch {
    return "";
  }
  const contributions = (explanation.evidence || []).filter((e) => e.type === "FEATURE_CONTRIBUTION");
  if (contributions.length === 0) return "";

  const maxMagnitude = Math.max(...contributions.map((c) => Math.abs(c.shap_value)), 0.001);
  const rows = contributions.map((c) => {
    const widthPct = (Math.abs(c.shap_value) / maxMagnitude) * 100;
    const direction = c.shap_value >= 0 ? "shap-positive" : "shap-negative";
    return `
      <div class="shap-row">
        <span class="shap-feature">${c.feature}</span>
        <span class="shap-bar-track">
          <span class="shap-bar ${direction}" style="width:${widthPct.toFixed(1)}%"></span>
        </span>
        <span class="shap-value ${direction}">${c.shap_value >= 0 ? "+" : ""}${c.shap_value.toFixed(2)}</span>
      </div>`;
  }).join("");

  return `
    <div class="shap-section">
      <div class="shap-title">Why the model scored it this way (real SHAP attributions)</div>
      ${rows}
    </div>`;
}

// Clears any previously generated narrative when the active claim changes, so
// switching from a flagged claim to a clean one never leaves the last claim's
// text on screen looking like it belongs to the new one.
function resetNarrative() {
  $("narrative-result").classList.add("hidden");
  $("narrative-loading").classList.add("hidden");
  $("narrative-error").classList.add("hidden");
  $("narrative-text").textContent = "";
  $("narrative-meta").textContent = "";
}

// Calls POST /score/narrative for the active claim (app/narrative.py: a local Ollama
// model renders the claim's own SHAP + shared-entity evidence into a sentence, checked
// against that same evidence so it can't mention a claim it wasn't shown), renders the
// result - or, if the model produced nothing grounded, the deterministic template
// summary it fell back to - and then records it as a permanent, hash-chained audit
// event (POST /api/claims/{id}/audit/narrative) exactly like a FRAUD_SCORED event:
// what an investigator read shouldn't just live in a browser tab and vanish on refresh.
// The audit call is best-effort - a claim still shows its narrative even if recording
// it fails, since the narrative itself is the primary thing being asked for here.
async function generateNarrative() {
  if (!state.activeClaimId) return;
  const claimId = state.activeClaimId;
  resetNarrative();
  $("narrative-loading").classList.remove("hidden");
  try {
    const result = await scoringApiPost("/score/narrative", { claim_id: claimId });
    $("narrative-text").textContent = result.narrative;
    const usedModel = result.model_version.startsWith("ollama:");
    $("narrative-meta").innerHTML = `
      <span class="narrative-badge ${usedModel ? "badge-model" : "badge-fallback"}">
        ${usedModel ? result.model_version : "template fallback (model output wasn't grounded)"}
      </span>
      <span class="narrative-latency">${(result.generation_ms / 1000).toFixed(1)}s</span>`;
    $("narrative-result").classList.remove("hidden");

    try {
      await api(`/api/claims/${claimId}/audit/narrative`, {
        method: "POST",
        body: JSON.stringify({
          narrative: result.narrative, grounded: result.grounded, modelVersion: result.model_version,
        }),
      });
      // Re-renders just the timeline, not the whole detail panel - reusing
      // loadClaimDetail()/renderClaimDetail() here would call resetNarrative()
      // and immediately wipe the text this function just showed above.
      if (state.activeClaimId === claimId) {
        const events = await api(`/api/claims/${claimId}/audit`);
        renderAuditTimeline(events);
      }
    } catch {
      // Best-effort: the narrative is already shown above even if recording it failed.
    }
  } catch (err) {
    $("narrative-error").textContent = err.message;
    $("narrative-error").classList.remove("hidden");
  } finally {
    $("narrative-loading").classList.add("hidden");
  }
}

// --- Wiring ------------------------------------------------------------

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("login-error").classList.add("hidden");
  try {
    await login($("username").value, $("password").value);
  } catch (err) {
    $("login-error").textContent = err.message;
    $("login-error").classList.remove("hidden");
  }
});

$("logout-btn").addEventListener("click", logout);

$("claim-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  $("claim-form-error").classList.add("hidden");
  const values = {
    claimantName: $("claimantName").value,
    policyNumber: $("policyNumber").value,
    claimAmount: Number($("claimAmount").value),
    incidentDate: $("incidentDate").value,
    claimantPhone: $("claimantPhone").value,
    claimantAddress: $("claimantAddress").value,
    repairShopName: $("repairShopName").value,
  };
  try {
    await submitClaim(values);
  } catch (err) {
    $("claim-form-error").textContent = err.message;
    $("claim-form-error").classList.remove("hidden");
  }
});

$("prefill-ring-btn").addEventListener("click", () => { $("claimantPhone").value = RING_DEMO_PHONE; });
$("prefill-clean-btn").addEventListener("click", () => {
  const random = Math.floor(600000000 + Math.random() * 399999999);
  $("claimantPhone").value = `+91${random}`;
});

$("verify-btn").addEventListener("click", () => {
  if (state.activeClaimId) verifyChain(state.activeClaimId);
});

$("narrative-btn").addEventListener("click", generateNarrative);

// --- Model & Evaluation panel ------------------------------------------

// Fetches a real, unauthenticated GET from the Python scoring service (a separate
// origin/port from the Java backend, hence its own small helper rather than reusing
// api() - no JWT involved, these endpoints just read tools/train_model.py's persisted
// artifacts). Throws with the backend's own error detail on a non-2xx response.
async function scoringApi(path) {
  const res = await fetch(`${SCORING_API_BASE}${path}`);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

// The POST counterpart of scoringApi, used only by /score/narrative - the one scoring-
// service call this frontend makes that isn't a plain artifact read.
async function scoringApiPost(path, body) {
  const res = await fetch(`${SCORING_API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const problem = await res.json().catch(() => ({}));
    throw new Error(problem.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

const ABLATION_ORDER = [
  ["tabular_only", "Tabular-only (no graph)"],
  ["plus_graph_features", "+ Graph features"],
  ["plus_calibration", "+ Calibration (live model)"],
];

// Builds the ablation table rows: AUPRC, precision/recall@k for a representative k, and
// the flag threshold each variant actually operates at - real numbers from the last
// `make train-model` run, not hardcoded example data.
function renderAblationTable(ablation) {
  const bestAuprc = Math.max(...Object.values(ablation).map((v) => v.auprc));
  const kValues = Object.keys(ablation.tabular_only.precision_recall_at_k);
  const midK = kValues[Math.floor(kValues.length / 2)];

  const rows = ABLATION_ORDER.map(([key, label]) => {
    const v = ablation[key];
    const pk = v.precision_recall_at_k[midK];
    const isBest = v.auprc === bestAuprc;
    return `
      <tr class="${isBest ? "best-row" : ""}">
        <td>${label}</td>
        <td>${v.auprc.toFixed(4)}</td>
        <td>${pk.precision.toFixed(3)}</td>
        <td>${pk.recall.toFixed(3)}</td>
        <td>${v.flag_threshold.toFixed(3)}</td>
      </tr>`;
  }).join("");

  return `
    <div class="eval-table-wrap">
      <table class="eval-table">
        <thead>
          <tr><th>Variant</th><th>AUPRC</th><th>Precision@${midK}</th><th>Recall@${midK}</th><th>Flag threshold</th></tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

// Renders the ring-injection ablation: recall on rings the model has NEVER seen any part
// of (built entirely within the test period - see tools/gen_rings.py --held-out-rings),
// tabular-only vs. with graph features. This is the headline experiment for why graph
// structure matters specifically for coordinated fraud, not fraud detection in general.
function renderRingInjection(ri) {
  if (!ri || !ri.held_out_claims) {
    return `<p class="muted">No held-out rings in this dataset.</p>`;
  }
  const tab = ri.tabular_only.recall_at_own_threshold;
  const graph = ri.plus_graph_features.recall_at_own_threshold;
  return `
    <p class="muted" style="margin-bottom:12px">
      ${ri.held_out_claims} claims across ${ri.held_out_rings} rings built entirely within the test
      period - the model never saw any part of these during training.
    </p>
    <div class="ring-injection-box">
      <div class="ri-card">
        <div class="ri-label">Tabular-only recall</div>
        <div class="ri-value bad">${(tab * 100).toFixed(1)}%</div>
        <div class="ri-sub">no entity-sharing information at all</div>
      </div>
      <div class="ri-card">
        <div class="ri-label">+ Graph features recall</div>
        <div class="ri-value good">${(graph * 100).toFixed(1)}%</div>
        <div class="ri-sub">k-core, Leiden, PPR, 2-hop aggregation</div>
      </div>
    </div>`;
}

// Renders tools/eval_narrative.py's persisted report: grounded rate, fallback rate, and
// latency over a real sample of FLAGged claims - real numbers from the last
// `make eval-narrative` run, same discipline as the ablation table above. Returns an
// empty string (not an error) when no report exists yet, since that's a legitimate
// "haven't run it on this checkout" state, not a failure of the rest of the panel.
function renderNarrativeEval(report) {
  if (!report) {
    return `<h3>Investigator narrative (local LLM)</h3>
      <p class="muted">No narrative evaluation yet - run <code>make eval-narrative</code>.</p>`;
  }
  return `
    <h3>Investigator narrative (local LLM, llama3.2:3b)</h3>
    <p class="muted" style="margin-bottom:12px">
      ${report.sample_size} real FLAGged claims, each narrative checked against its own
      evidence for invented claim ids before being shown to an investigator.
    </p>
    <div class="ring-injection-box">
      <div class="ri-card">
        <div class="ri-label">Grounded rate</div>
        <div class="ri-value good">${(report.grounded_rate * 100).toFixed(0)}%</div>
        <div class="ri-sub">${report.fallback_rate > 0
          ? `${(report.fallback_rate * 100).toFixed(0)}% fell back to the template`
          : "0 fell back to the template"}</div>
      </div>
      <div class="ri-card">
        <div class="ri-label">Latency (median / p95)</div>
        <div class="ri-value">${(report.latency_ms.median / 1000).toFixed(1)}s / ${(report.latency_ms.p95 / 1000).toFixed(1)}s</div>
        <div class="ri-sub">on-demand, one claim at a time</div>
      </div>
    </div>`;
}

// Loads /model/metadata, /model/eval-report, and (best-effort) /narrative/eval-report,
// and renders the full panel. Called each time the panel is opened, so it always
// reflects whatever tools/train_model.py and tools/eval_narrative.py last wrote.
async function openModelPanel() {
  $("model-panel-backdrop").classList.remove("hidden");
  const body = $("model-panel-body");
  body.innerHTML = `<p class="muted">Loading&hellip;</p>`;
  try {
    const [metadata, report] = await Promise.all([
      scoringApi("/model/metadata"),
      scoringApi("/model/eval-report"),
    ]);
    // Narrative eval is fetched separately and tolerantly - a checkout that has trained
    // the Tier 1 model but never run `make eval-narrative` should still see the rest of
    // this panel, not a blank error screen for an unrelated, optional report.
    const narrativeReport = await scoringApi("/narrative/eval-report").catch(() => null);
    body.innerHTML = `
      <div class="model-meta-row">
        <div><dt>Model version</dt><dd>${metadata.model_version}</dd></div>
        <div><dt>Trained at</dt><dd>${formatDateTime(metadata.trained_at)}</dd></div>
        <div><dt>Flag threshold</dt><dd>${metadata.flag_threshold}</dd></div>
        <div><dt>Review threshold</dt><dd>${metadata.review_threshold}</dd></div>
      </div>
      <h3>Ablation: does graph structure actually help?</h3>
      ${renderAblationTable(report.ablation)}
      <h3>Ring-injection ablation (held-out, never-seen rings)</h3>
      ${renderRingInjection(report.ring_injection_ablation)}
      ${renderNarrativeEval(narrativeReport)}
    `;
  } catch (err) {
    body.innerHTML = `<p class="error-text">${err.message}</p>`;
  }
}

$("model-info-btn").addEventListener("click", openModelPanel);
$("model-panel-close").addEventListener("click", () => $("model-panel-backdrop").classList.add("hidden"));
$("model-panel-backdrop").addEventListener("click", (e) => {
  if (e.target.id === "model-panel-backdrop") $("model-panel-backdrop").classList.add("hidden");
});
