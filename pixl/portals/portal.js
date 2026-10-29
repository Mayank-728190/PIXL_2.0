"use strict";
const panel = document.body.dataset.panel;
const master = panel === "master";
const $ = id => document.getElementById(id);
const selected = new Map();
let media = [], screens = [], agencies = [], refreshing = false, signedIn = false;
let activeUploads = 0;
let campaignData = [], pollFailures = 0, pollTimer, refreshCount = 0;
let sessionGeneration = 0, refreshQueued = false, jobsRestored = false;
const processingJobs = new Map();
const jobStorageKey = `pixl:${panel}:processing`;
const observations = [];
const svgNS = "http://www.w3.org/2000/svg";
function svgNode(tag, attributes) {
  const element = document.createElementNS(svgNS, tag);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, String(value));
  return element;
}
function renderOverview() {
  const online = screens.filter(s => s.is_online).length;
  const attention = screens.length - online;
  const stats = [
    ["Total screens", screens.length, master ? "Across your entire network" : "Assigned to your agency"],
    ["Online now", online, "Based on latest device activity"],
    ["Needs attention", attention, "Offline or awaiting pairing"],
    master ? ["Active agencies", agencies.filter(a => a.status === "ACTIVE").length, `${agencies.length} agencies in your workspace`] : ["Published campaigns", campaignData.filter(c => c.status === "PUBLISHED" && new Date(c.end_time) > new Date()).length, `${media.filter(m => m.status === "READY").length} media files ready to use`]
  ];
  $("metrics").replaceChildren(...stats.map(([label, value, hint]) => {
    const item = node("article", undefined, "metric");
    item.append(node("span", label, "metric-label"), node("strong", String(value)), node("small", hint));
    return item;
  }));
  observations.push({ online, total: screens.length });
  if (observations.length > 30) observations.shift();
  const chart = $("pulse-chart"); chart.replaceChildren();
  const ceiling = Math.max(1, ...observations.map(o => o.total));
  for (const y of [20, 70, 120]) chart.append(svgNode("line", { x1: 0, x2: 600, y1: y, y2: y, stroke: "#e8ecdf", "stroke-dasharray": "4 5" }));
  const points = observations.map((o, i) => `${observations.length === 1 ? 600 : i * 600 / (observations.length - 1)},${120 - o.online / ceiling * 100}`);
  chart.append(svgNode("polyline", { points: points.join(" "), fill: "none", stroke: "#658542", "stroke-width": 3, "stroke-linejoin": "round", "vector-effect": "non-scaling-stroke" }));
  const lastY = 120 - online / ceiling * 100;
  chart.append(svgNode("circle", { cx: 600, cy: lastY, r: 4, fill: "#315d3a" }));
  chart.setAttribute("aria-label", `Online screens over ${observations.length} observations this session. Latest: ${online} of ${screens.length}.`);
  const ring = svgNode("svg", { viewBox: "0 0 120 120", role: "img", "aria-label": `${online} online, ${attention} need attention` });
  ring.append(svgNode("circle", { cx: 60, cy: 60, r: 46, fill: "none", stroke: "#edf0e5", "stroke-width": 10 }));
  const ratio = screens.length ? online / screens.length : 0;
  ring.append(svgNode("circle", { cx: 60, cy: 60, r: 46, fill: "none", stroke: "#658542", "stroke-width": 10, "stroke-dasharray": `${ratio * 289} 289`, transform: "rotate(-90 60 60)" }));
  const percentage = svgNode("text", { x: 60, y: 64, "text-anchor": "middle", fill: "#242923", "font-size": 23, "font-weight": 600 });
  percentage.textContent = screens.length ? `${Math.round(ratio * 100)}%` : "—"; ring.append(percentage);
  const legend = node("div", undefined, "health-legend");
  legend.append(node("span", `${online} Online`), node("span", `${attention} Need attention`));
  $("health-chart").replaceChildren(ring, legend);
  $("health-description").textContent = screens.length ? "Connection health now, not proof of playback." : "Provision your first screen to see network health.";
}
function openMediaActions(asset) {
  $("media-action-name").textContent = asset.filename;
  const actions = $("media-action-buttons"); actions.replaceChildren();
  if (asset.status === "READY") {
    actions.append(button("Use in a new campaign", async () => {
      if (!selected.has(asset.id)) selected.set(asset.id, { mode: asset.mime_type.startsWith("video/") ? "FULL_CLIP" : "IMAGE_DEFAULT", seconds: Math.max(1, Math.round(asset.duration_ms / 1000) || 10) });
      $("media-actions").close(); renderMedia(true); location.hash = "composer";
      $("campaign-form").elements.name.focus();
    }), button(selected.has(asset.id) ? "Remove from selection" : "Add to selection", async () => {
      if (selected.has(asset.id)) selected.delete(asset.id);
      else selected.set(asset.id, { mode: asset.mime_type.startsWith("video/") ? "FULL_CLIP" : "IMAGE_DEFAULT", seconds: Math.max(1, Math.round(asset.duration_ms / 1000) || 10) });
      $("media-actions").close(); renderMedia(true);
    }));
  } else actions.append(node("p", "This file must finish validation before it can be used."));
  $("media-actions").showModal();
}
const uploadQueue = [];
function node(tag, text, cls) {
  const item = document.createElement(tag);
  if (text !== undefined) item.textContent = text;
  if (cls) item.className = cls;
  return item;
}
function announce(message, error = false) {
  $("notice").textContent = message;
  $("notice").classList.toggle("error", error);
}
function errorMessage(body) {
  if (body?.error?.message) return body.error.message;
  if (Array.isArray(body?.detail)) return body.detail.map(e => `${e.loc.slice(1).join(" / ")}: ${e.msg}`).join("\n");
  return typeof body?.detail === "string" ? body.detail : "Request failed. Please try again.";
}
async function api(path, options = {}) {
  const generation = sessionGeneration;
  const response = await fetch(path, {
    signal: AbortSignal.timeout(path.endsWith("/process") || path.endsWith("/finalize") ? 180000 : 30000),
    credentials: "same-origin", ...options,
    headers: { "Content-Type": "application/json", ...options.headers }
  });
  const body = await response.json().catch(() => ({}));
  if (generation !== sessionGeneration) throw new Error("Session changed. Please try again.");
  if (!response.ok) {
    if (response.status === 401 && generation === sessionGeneration) setSignedIn(false);
    const requestId = response.headers.get("X-Request-ID");
    const error = new Error(`${errorMessage(body)}${response.status >= 500 && requestId ? ` (Reference: ${requestId})` : ""}`);
    error.status = response.status;
    throw error;
  }
  return body;
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body) });
function setSignedIn(value) {
  signedIn = value;
  $("workspace").hidden = !value;
  $("login").hidden = value || panel === "invitation";
  $("logout").hidden = !value;
  if (!value) {
    sessionGeneration++; selected.clear(); processingJobs.clear(); uploadQueue.length = 0;
    media = []; screens = []; agencies = []; campaignData = []; observations.length = 0;
    jobsRestored = false; persistJobs();
    for (const id of ["media-rows", "screens", "campaign-rows", "agency-rows", "upload-progress"]) $(id).replaceChildren();
    $("invite-result").hidden = true; $("invitation-link").value = "";
    if ($("media-actions").open) $("media-actions").close();
    clearTimeout(pollTimer); pollTimer = null;
  } else {
    if (!jobsRestored) { jobsRestored = true; restoreJobs(); }
    if (!pollTimer) schedulePoll();
  }
}
function button(label, action) {
  const result = node("button", label);
  result.type = "button";
  result.addEventListener("click", async () => {
    result.disabled = true;
    try { await action(); } catch (error) { announce(error.message, true); }
    finally { result.disabled = false; }
  });
  return result;
}
function fillOptions(select, rows, chosen, label) {
  select.replaceChildren(new Option("Choose an agency", ""));
  for (const row of rows) select.add(new Option(label(row), row.id));
  if (chosen) select.value = chosen;
}
function badge(text) { return node("span", text, `badge ${["OFFLINE", "SUSPENDED"].includes(text) ? "offline" : ""}`); }
function cell(row, text) { const td = node("td", text); row.append(td); return td; }
function formatDate(value) { return value ? new Date(value).toLocaleString() : "Not received"; }
function renderScreens() {
  // Avoid destroying a keyboard-focused action selector while polling.
  if ($("screens").contains(document.activeElement) || $("campaign-targets").contains(document.activeElement) || $("claim-target") === document.activeElement) return;
  $("screens").replaceChildren();
  const targets = new Set([...$("campaign-targets").querySelectorAll("input:checked")].map(i => i.value));
  $("campaign-targets").replaceChildren();
  const claimValue = $("claim-target").value;
  $("claim-target").replaceChildren(new Option("Choose an assigned screen", ""));
  for (const screen of screens) {
    const row = node("tr");
    const name = cell(row, screen.name);
    name.append(node("small", `#${screen.screen_number || "—"} · ${screen.id.slice(0, 8)}`));
    cell(row, agencies.find(a => a.id === screen.organization_id)?.name || (screen.organization_id ? "Assigned" : "Unassigned"));
    const status = screen.is_online ? screen.status : (["UNREGISTERED", "UNPAIRED"].includes(screen.status) ? screen.status : "OFFLINE");
    cell(row).append(badge(status));
    const activity = cell(row, formatDate(screen.last_seen_at));
    activity.append(node("small", `Heartbeat: ${formatDate(screen.last_heartbeat_at)}`));
    const actions = cell(row);
    if (master) {
      const assignment = node("select");
      assignment.setAttribute("aria-label", `Assign ${screen.name} to agency`);
      fillOptions(assignment, agencies.filter(a => a.status === "ACTIVE"), screen.organization_id, a => a.name);
      actions.append(assignment, button("Assign", async () => {
        if (!assignment.value) throw new Error("Choose the target agency.");
        if (!confirm("Change this screen's assignment? Existing device credentials and campaign assignments will be revoked.")) return;
        await post(`/api/v1/master/screens/${screen.id}/assign`, { organization_id: assignment.value });
        announce("Screen assignment saved."); await refresh();
      }));
    } else {
      $("claim-target").add(new Option(screen.name, screen.id));
      const label = node("label");
      const checkbox = node("input"); checkbox.type = "checkbox"; checkbox.value = screen.id;
      checkbox.name = "screen_ids"; checkbox.checked = targets.has(screen.id);
      label.append(checkbox, document.createTextNode(screen.name)); $("campaign-targets").append(label);
    }
    actions.append(button("Playback", async () => {
      const status = await api(`/api/v1/${panel}/screens/${screen.id}/playback`);
      announce(`${screen.name}: ${status.current_campaign?.name || "No active campaign"}. ${status.is_online ? "Online" : "Offline"}.`);
    }), button("Stop ad", async () => {
      if (!confirm(`Stop the current campaign on ${screen.name}?`)) return;
      const result = await post(`/api/v1/${panel}/screens/${screen.id}/stop-ad`, {});
      announce(result.message); await refresh();
    }));
    $("screens").append(row);
  }
  $("claim-target").value = claimValue;
  $("fleet-count").textContent = `${screens.length} screens · ${screens.filter(s => s.is_online).length} online`;
  if (!screens.length) { const row = node("tr"); const td = cell(row, "No screens assigned yet."); td.colSpan = 5; $("screens").append(row); }
}
function renderAgencies() {
  $("agency-rows").replaceChildren();
  for (const agency of agencies) {
    const row = node("tr"); cell(row, agency.name); cell(row, agency.slug);
    cell(row).append(badge(agency.status)); cell(row, String(agency.max_screens));
    const actions = cell(row);
    if (agency.status === "ACTIVE") actions.append(button("Suspend", async () => {
      if (!confirm(`Suspend ${agency.name}? Users and devices will lose access.`)) return;
      await post(`/api/v1/master/agencies/${agency.id}/suspend`, {}); await refresh();
    }));
    actions.append(button("Admin accounts", async () => {
      const users = await api(`/api/v1/master/agencies/${agency.id}/admins`);
      $("media-action-name").textContent = `${agency.name} · Administrator access`;
      const content = $("media-action-buttons"); content.replaceChildren();
      for (const user of users) {
        const entry = node("div"); entry.append(node("p", `${user.email} · ${user.status}`));
        if (user.status !== "DELETED") entry.append(button("Delete admin access", async () => {
          if (!confirm(`Permanently revoke admin access for ${user.email}? This retains audit and campaign records.`)) return;
          await api(`/api/v1/master/agencies/${agency.id}/admins/${user.id}`, { method: "DELETE" });
          $("media-actions").close(); announce("Admin access deleted and sessions revoked.");
        }));
        content.append(entry);
      }
      if (!users.length) content.append(node("p", "No activated administrators yet."));
      if (agency.status === "ACTIVE") {
        const inviteForm = node("form"), label = node("label", "Invite another administrator"), email = node("input");
        email.type = "email"; email.required = true; email.name = "email"; email.placeholder = "admin@agency.com";
        label.append(email);
        const submit = node("button", "Create admin invitation"); submit.type = "submit";
        inviteForm.append(label, submit); content.append(inviteForm);
        inviteForm.addEventListener("submit", async event => {
          event.preventDefault(); submit.disabled = true;
          try {
            const result = await post(`/api/v1/master/agencies/${agency.id}/admins`, { email: email.value });
            $("invitation-link").value = result.invitation_link; $("invite-result").hidden = false;
            $("media-actions").close(); location.hash = "agencies";
            announce("Admin invitation created. Share the private link below; it expires in 24 hours.");
          } catch (error) {
            let message = inviteForm.querySelector(".field-error");
            if (!message) { message = node("p", undefined, "field-error"); message.setAttribute("role", "alert"); inviteForm.append(message); }
            message.textContent = error.message;
          } finally { submit.disabled = false; }
        });
      }
      $("media-actions").showModal();
    }));
    $("agency-rows").append(row);
  }
  if (document.activeElement !== $("screen-agency")) fillOptions($("screen-agency"), agencies.filter(a => a.status === "ACTIVE"), $("screen-agency").value, a => a.name);
}
function selectionSummary() {
  $("selection-summary").textContent = selected.size ? `${selected.size} selected, in playback order: ${[...selected.keys()].map(id => media.find(m => m.id === id)?.filename || id).join(" → ")}` : "Select ready media above. Selection order becomes playback order.";
}
function renderMedia(force = false) {
  if (!force && $("media-rows").contains(document.activeElement)) return;
  $("media-rows").replaceChildren();
  const search = $("media-search").value.toLowerCase();
  for (const asset of media.filter(a => a.filename.toLowerCase().includes(search))) {
    const row = node("tr"), checkbox = node("input"); checkbox.type = "checkbox";
    checkbox.checked = selected.has(asset.id); checkbox.disabled = asset.status !== "READY";
    checkbox.setAttribute("aria-label", `Select ${asset.filename}`);
    const video = asset.mime_type.startsWith("video/");
    const config = selected.get(asset.id) || { mode: video ? "FULL_CLIP" : "IMAGE_DEFAULT", seconds: Math.max(1, Math.round(asset.duration_ms / 1000) || 10) };
    checkbox.addEventListener("change", () => { if (checkbox.checked) selected.set(asset.id, config); else selected.delete(asset.id); selectionSummary(); });
    cell(row).append(checkbox);
    const filename = cell(row);
    if (asset.thumbnail_url) {
      const preview = node("img"); preview.src = asset.thumbnail_url; preview.alt = "";
      preview.loading = "lazy"; preview.className = "media-preview"; filename.append(preview);
    }
    filename.append(document.createTextNode(asset.filename));
    cell(row, `${asset.mime_type} · ${asset.width} × ${asset.height}`); cell(row).append(badge(asset.status));
    const mode = node("select");
    for (const value of video ? ["FULL_CLIP", "CUSTOM_DURATION"] : ["IMAGE_DEFAULT", "CUSTOM_DURATION"]) mode.add(new Option(value.replaceAll("_", " "), value));
    mode.value = config.mode; mode.setAttribute("aria-label", `Playback mode for ${asset.filename}`);
    mode.addEventListener("change", () => { config.mode = mode.value; });
    const duration = node("input"); duration.type = "number"; duration.min = "1"; duration.max = "86400"; duration.value = config.seconds;
    duration.setAttribute("aria-label", `Seconds for ${asset.filename}`);
    duration.addEventListener("input", () => { config.seconds = Number(duration.value); });
    duration.disabled = config.mode === "FULL_CLIP";
    mode.addEventListener("change", () => { duration.disabled = mode.value === "FULL_CLIP"; });
    cell(row).append(mode); cell(row).append(duration);
    const menu = button("•••", async () => openMediaActions(asset));
    menu.setAttribute("aria-label", `Actions for ${asset.filename}`); menu.setAttribute("aria-haspopup", "dialog");
    cell(row).append(menu); $("media-rows").append(row);
  }
  if (!$("media-rows").children.length) { const row = node("tr"); const td = cell(row, media.length ? "No media matches your search." : "Your library is empty. Upload files above to get started."); td.colSpan = 7; $("media-rows").append(row); }
  selectionSummary();
}
function renderCampaigns(campaigns, force = false) {
  if (!force && $("campaign-rows").contains(document.activeElement)) return;
  $("campaign-rows").replaceChildren();
  for (const campaign of campaigns) {
    const now = new Date(), expired = new Date(campaign.end_time) <= now;
    const status = campaign.status === "PUBLISHED" ? (expired ? "ENDED" : new Date(campaign.start_time) > now ? "SCHEDULED" : "LIVE WINDOW") : campaign.status;
    const row = node("tr"); cell(row, campaign.name); cell(row).append(badge(status));
    cell(row, String(campaign.priority)); cell(row, `${formatDate(campaign.start_time)} — ${formatDate(campaign.end_time)}`);
    cell(row, String(campaign.assignments.length));
    const actions = cell(row);
    if (["DRAFT", "APPROVED"].includes(campaign.status) && !expired) actions.append(button("Publish draft", async () => {
      await post(`/api/v1/agency/campaigns/${campaign.id}/publish`, {});
      announce("Saved campaign published."); await refresh();
    }));
    $("campaign-rows").append(row);
  }
  if (!campaigns.length) { const row = node("tr"); cell(row, "No campaigns yet. Select media and choose a schedule above.").colSpan = 6; $("campaign-rows").append(row); }
}
async function refresh(full = true) {
  if (panel === "invitation") return;
  if (refreshing) { refreshQueued ||= full; return; }
  refreshing = true;
  const generation = sessionGeneration;
  $("workspace").setAttribute("aria-busy", "true");
  try {
    if (master) {
      const rows = await Promise.all([api("/api/v1/master/screens"), api("/api/v1/master/agencies")]);
      if (generation !== sessionGeneration) return;
      [screens, agencies] = rows; renderAgencies();
    } else {
      if (full || refreshCount % 6 === 0) {
        const rows = await Promise.all([api("/api/v1/agency/screens"), api("/api/v1/agency/media"), api("/api/v1/agency/campaigns")]);
        if (generation !== sessionGeneration) return;
        [screens, media, campaignData] = rows; renderMedia(); renderCampaigns(campaignData, full);
      } else {
        const rows = await api("/api/v1/agency/screens");
        if (generation !== sessionGeneration) return;
        screens = rows;
      }
    }
    renderScreens(); renderOverview(); pollFailures = 0; refreshCount++; setSignedIn(true);
    if (!master) await updateProcessingJobs();
    if (generation !== sessionGeneration) return;
    $("connection").textContent = `Updated ${new Date().toLocaleTimeString()}`;
    $("connection").classList.remove("stale");
  } catch (error) {
    if (generation !== sessionGeneration) return;
    pollFailures++;
    $("connection").textContent = "Connection lost — showing last known data";
    $("connection").classList.add("stale");
    if (error.status !== 401) announce(error.message, true);
  } finally {
    refreshing = false; $("workspace").setAttribute("aria-busy", "false");
    if (refreshQueued) { refreshQueued = false; if (signedIn) queueMicrotask(() => refresh()); }
  }
}
function bindForm(id, action) {
  $(id).addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget, submit = form.querySelector("button[type=submit]");
    submit.disabled = true; announce("");
    try { await action(Object.fromEntries(new FormData(form)), form); }
    catch (error) {
      announce(error.message, true);
      if (id === "campaign-form") { $("campaign-error").textContent = error.message; $("campaign-error").scrollIntoView({ block: "center" }); }
    }
    finally { submit.disabled = false; }
  });
}
bindForm("login-form", async (data, form) => {
  if (!data.totp_code) delete data.totp_code;
  await post(`/api/v1/auth/${panel}/login`, data);
  form.reset(); await refresh();
});
bindForm("invitation-form", async (data, form) => {
  await post("/api/v1/auth/invitation/accept", data); form.reset();
  history.replaceState(null, "", "/accept-invitation");
  announce("Account activated. You can now sign in to the agency portal.");
});
bindForm("provision-agency", async (data, form) => {
  data.max_screens = Number(data.max_screens);
  const result = await post("/api/v1/master/agencies", data);
  $("invitation-link").value = result.invitation_link; $("invite-result").hidden = false;
  form.reset(); announce("Agency created. Share the invitation privately."); await refresh();
});
bindForm("provision-screen", async (data, form) => { await post("/api/v1/master/screens", data); form.reset(); announce("Screen provisioned. Complete pairing on the device."); await refresh(); });
bindForm("claim-screen", async (data, form) => { const result = await post("/api/v1/agency/screens/claim", data); form.reset(); announce(result.message); await refresh(); });
bindForm("campaign-form", async data => {
  $("campaign-error").textContent = "";
  data.name = data.name.trim();
  if (data.name.length < 2) throw new Error("Enter a campaign name with at least two characters.");
  if (!Number.isFinite(new Date(data.start_time).getTime()) || !Number.isFinite(new Date(data.end_time).getTime())) throw new Error("Choose valid start and end dates.");
  if (!selected.size) throw new Error("Select at least one READY media file.");
  const ids = [...$("campaign-targets").querySelectorAll("input:checked")].map(i => i.value);
  if (!ids.length) throw new Error("Choose at least one assigned screen.");
  if (new Date(data.end_time) <= new Date(data.start_time)) throw new Error("End time must be after start time.");
  const items = [...selected].map(([id, config], index) => {
    const asset = media.find(m => m.id === id);
    if (!asset || asset.status !== "READY") throw new Error("A selected asset is no longer ready. Refresh the library.");
    if (!Number.isFinite(config.seconds) || config.seconds < 1 || config.seconds > 86400) throw new Error("Media duration must be between 1 and 86400 seconds.");
    const duration = config.mode === "FULL_CLIP" ? asset.duration_ms : config.seconds * 1000;
    return { media_id: id, sort_order: index, duration_mode: config.mode, configured_duration_ms: Math.max(1, Math.round(duration)) };
  });
  const playlist = await post("/api/v1/agency/playlists", { name: data.name, items });
  const campaign = await post("/api/v1/agency/campaigns", { name: data.name, priority: Number(data.priority), playlist_id: playlist.id, screen_ids: ids, start_time: new Date(data.start_time).toISOString(), end_time: new Date(data.end_time).toISOString() });
  try { await post(`/api/v1/agency/campaigns/${campaign.id}/publish`, {}); }
  catch (error) {
    await refresh();
    throw new Error(`Draft ${campaign.name} was saved. Use “Publish draft” in the campaign list to retry without creating a duplicate. ${error.message}`);
  }
  selected.clear(); announce("Campaign published. Devices receive it on their next manifest refresh."); await refresh();
});
function uploadBytes(url, file, progress) {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest(); request.open("PUT", url); request.timeout = 300000;
    request.upload.onprogress = event => { if (event.lengthComputable) progress.value = Math.round(100 * event.loaded / event.total); };
    request.onload = () => request.status >= 200 && request.status < 300 ? resolve() : reject(new Error("Upload rejected. Check size, expiry and storage quota."));
    request.onerror = () => reject(new Error("Network error during upload."));
    request.ontimeout = () => reject(new Error("Upload timed out.")); request.send(file);
  });
}
function persistJobs() {
  try { sessionStorage.setItem(jobStorageKey, JSON.stringify([...processingJobs.values()].map(job => ({ ticketId: job.ticketId, filename: job.filename })))); }
  catch { /* Processing still works when browser storage is unavailable. */ }
}
function restoreJobs() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(jobStorageKey) || "[]");
    if (!Array.isArray(saved)) return;
    for (const item of saved.slice(0, 100)) {
      if (typeof item.ticketId !== "string" || typeof item.filename !== "string") continue;
      const row = node("li"), label = node("span", `${item.filename}: checking processing status`), progress = node("progress");
      row.append(label, progress); $("upload-progress").append(row);
      processingJobs.set(item.ticketId, { ...item, row, label, progress });
    }
  } catch { /* Ignore malformed or unavailable session storage. */ }
}
async function updateProcessingJobs() {
  const generation = sessionGeneration;
  await Promise.allSettled([...processingJobs.values()].map(async job => {
    if (job.checking) return;
    job.checking = true;
    try {
      let status = await api(`/api/v1/agency/media/uploads/${encodeURIComponent(job.ticketId)}`);
      if (generation !== sessionGeneration) return;
      if (status.status === "UPLOADED") status = await post("/api/v1/agency/media/process", { ticket_id: job.ticketId });
      if (generation !== sessionGeneration) return;
      if (status.status === "FINALIZED") {
        job.label.textContent = `${job.filename}: ready`; job.progress.max = 100; job.progress.value = 100;
        processingJobs.delete(job.ticketId); persistJobs(); await refresh();
      } else if (["FAILED", "EXPIRED"].includes(status.status)) {
        job.label.textContent = `${job.filename}: ${status.error || "Upload expired. Please upload again."}`;
        job.progress.remove(); processingJobs.delete(job.ticketId); persistJobs();
        if (job.file) job.row.append(button("Upload again", async () => { uploadQueue.push({ file: job.file, row: job.row }); pumpUploads(); }));
      } else {
        job.progress.removeAttribute("value");
        job.label.textContent = `${job.filename}: ${status.status === "QUEUED" ? status.attempts ? "queued for retry" : "queued for validation" : "validating and processing"}${status.attempts ? ` · attempt ${status.attempts} of 3` : ""}`;
      }
    } catch (error) {
      if (generation !== sessionGeneration) return;
      job.label.textContent = `${job.filename}: status unavailable — will retry. ${error.message}`;
      if (error.status === 404) { processingJobs.delete(job.ticketId); job.progress.remove(); persistJobs(); }
    } finally { job.checking = false; }
  }));
}
async function uploadFile(file, row) {
  const generation = sessionGeneration;
  const label = node("span", `${file.name}: preparing`), progress = node("progress"); progress.max = 100; progress.value = 0;
  progress.setAttribute("aria-label", `Upload progress for ${file.name}`); row.replaceChildren(label, progress);
  try {
    if (!file.size || file.size > 262144000) throw new Error("Choose a non-empty file of 250 MB or less.");
    if (!["image/png", "image/jpeg", "image/webp", "video/mp4", "video/webm"].includes(file.type)) throw new Error("Choose a PNG, JPEG, WebP, MP4 or WebM file.");
    const ticket = await post("/api/v1/agency/media/upload-ticket", { filename: file.name, size_bytes: file.size, declared_mime: file.type });
    if (generation !== sessionGeneration) return;
    label.textContent = `${file.name}: uploading`; await uploadBytes(ticket.presigned_upload_url, file, progress);
    if (generation !== sessionGeneration) return;
    label.textContent = `${file.name}: queued for validation`; progress.removeAttribute("value");
    processingJobs.set(ticket.ticket_id, { ticketId: ticket.ticket_id, filename: file.name, file, row, label, progress });
    persistJobs();
    // The status loop requests processing using the same ticket. A response lost
    // during publication is recoverable without uploading duplicate bytes.
    await updateProcessingJobs();
  } catch (error) {
    if (generation !== sessionGeneration) return;
    label.textContent = `${file.name}: ${error.message}`;
    row.append(button("Retry", async () => { uploadQueue.push({ file, row }); pumpUploads(); }));
  }
}
function pumpUploads() {
  while (activeUploads < 2 && uploadQueue.length) {
    const { file, row } = uploadQueue.shift(); activeUploads++;
    uploadFile(file, row).finally(() => { activeUploads--; pumpUploads(); });
  }
}
$("files").addEventListener("change", event => {
  for (const file of event.target.files) { const row = node("li", `${file.name}: queued`); $("upload-progress").append(row); uploadQueue.push({ file, row }); }
  event.target.value = ""; pumpUploads();
});
$("media-search").addEventListener("input", () => renderMedia());
$("refresh").addEventListener("click", () => refresh());
$("close-media-actions").addEventListener("click", () => $("media-actions").close());
$("compose-selected").addEventListener("click", event => {
  if (!selected.size) { event.preventDefault(); announce("Select ready media in the library first.", true); $("media-search").focus(); }
});
function updateNavigation() {
  for (const link of document.querySelectorAll('nav a')) {
    if (link.hash === (location.hash || "#overview")) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}
window.addEventListener("hashchange", updateNavigation); updateNavigation();
function schedulePoll() {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    pollTimer = null;
    if (signedIn && !document.hidden) await refresh(false);
    if (signedIn) schedulePoll();
  }, Math.min(60000, 5000 * 2 ** Math.min(pollFailures, 4)) + Math.random() * 750);
}
document.addEventListener("visibilitychange", () => { if (signedIn && !document.hidden) { refresh(false); schedulePoll(); } });
window.addEventListener("online", () => { if (signedIn) { refresh(); schedulePoll(); } });
$("copy-invitation").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText($("invitation-link").value); announce("Invitation copied. Share it privately."); }
  catch { $("invitation-link").select(); announce("Select and copy the invitation manually."); }
});
$("logout").addEventListener("click", async () => {
  try { await post(`/api/v1/auth/logout?panel=${panel}`, {}); selected.clear(); setSignedIn(false); announce("Signed out."); }
  catch (error) { announce(error.message, true); }
});
for (const element of document.querySelectorAll("[data-master]")) element.hidden = !master;
for (const element of document.querySelectorAll("[data-agency]")) element.hidden = master || panel === "invitation";
if (panel === "invitation") {
  $("login").hidden = true; $("invitation").hidden = false;
  $("invitation-form").elements.invitation_token.value = new URLSearchParams(location.search).get("token") || "";
  // Remove bearer invitation tokens from browser history after reading them.
  history.replaceState(null, "", "/accept-invitation");
} else {
  const localDate = date => new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  $("campaign-form").elements.start_time.value = localDate(new Date());
  $("campaign-form").elements.end_time.value = localDate(new Date(Date.now() + 86400000));
  refresh();
}
