"use strict";
const panel = document.body.dataset.panel;
const master = panel === "master";
const $ = id => document.getElementById(id);
const selected = new Map();
let media = [], screens = [], agencies = [], refreshing = false, signedIn = false;
let activeUploads = 0;
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
  const response = await fetch(path, {
    credentials: "same-origin", ...options,
    headers: { "Content-Type": "application/json", ...options.headers }
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) setSignedIn(false);
    const error = new Error(errorMessage(body));
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
  if ($("screens").contains(document.activeElement)) return;
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
    cell(row, formatDate(screen.last_seen_at));
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
    $("agency-rows").append(row);
  }
  fillOptions($("screen-agency"), agencies.filter(a => a.status === "ACTIVE"), $("screen-agency").value, a => a.name);
}
function selectionSummary() {
  $("selection-summary").textContent = selected.size ? `${selected.size} selected, in playback order: ${[...selected.keys()].map(id => media.find(m => m.id === id)?.filename || id).join(" → ")}` : "Select ready media above. Selection order becomes playback order.";
}
function renderMedia() {
  if ($("media-rows").contains(document.activeElement)) return;
  $("media-rows").replaceChildren();
  const search = $("media-search").value.toLowerCase();
  for (const asset of media.filter(a => a.filename.toLowerCase().includes(search))) {
    const row = node("tr"), checkbox = node("input"); checkbox.type = "checkbox";
    checkbox.checked = selected.has(asset.id); checkbox.disabled = asset.status !== "READY";
    checkbox.setAttribute("aria-label", `Select ${asset.filename}`);
    const video = asset.mime_type.startsWith("video/");
    const config = selected.get(asset.id) || { mode: video ? "FULL_CLIP" : "IMAGE_DEFAULT", seconds: Math.max(1, Math.round(asset.duration_ms / 1000) || 10) };
    checkbox.addEventListener("change", () => { if (checkbox.checked) selected.set(asset.id, config); else selected.delete(asset.id); selectionSummary(); });
    cell(row).append(checkbox); cell(row, asset.filename);
    cell(row, `${asset.mime_type} · ${asset.width} × ${asset.height}`); cell(row).append(badge(asset.status));
    const mode = node("select");
    for (const value of video ? ["FULL_CLIP", "CUSTOM_DURATION"] : ["IMAGE_DEFAULT", "CUSTOM_DURATION"]) mode.add(new Option(value.replaceAll("_", " "), value));
    mode.value = config.mode; mode.setAttribute("aria-label", `Playback mode for ${asset.filename}`);
    mode.addEventListener("change", () => { config.mode = mode.value; });
    const duration = node("input"); duration.type = "number"; duration.min = "1"; duration.max = "86400"; duration.value = config.seconds;
    duration.setAttribute("aria-label", `Seconds for ${asset.filename}`);
    duration.addEventListener("input", () => { config.seconds = Number(duration.value); });
    cell(row).append(mode); cell(row).append(duration); $("media-rows").append(row);
  }
  selectionSummary();
}
function renderCampaigns(campaigns) {
  $("campaign-rows").replaceChildren();
  for (const campaign of campaigns) {
    const row = node("tr"); cell(row, campaign.name); cell(row).append(badge(campaign.status));
    cell(row, String(campaign.priority)); cell(row, `${formatDate(campaign.start_time)} — ${formatDate(campaign.end_time)}`);
    cell(row, String(campaign.assignments.length)); $("campaign-rows").append(row);
  }
}
async function refresh() {
  if (refreshing || panel === "invitation") return;
  refreshing = true;
  try {
    if (master) {
      [screens, agencies] = await Promise.all([api("/api/v1/master/screens"), api("/api/v1/master/agencies")]);
      renderAgencies();
    } else {
      let campaigns;
      [screens, media, campaigns] = await Promise.all([api("/api/v1/agency/screens"), api("/api/v1/agency/media"), api("/api/v1/agency/campaigns")]);
      renderMedia(); renderCampaigns(campaigns);
    }
    renderScreens(); setSignedIn(true);
    $("connection").textContent = `Updated ${new Date().toLocaleTimeString()}`;
    $("connection").classList.remove("stale");
  } catch (error) {
    $("connection").textContent = "Connection lost — showing last known data";
    $("connection").classList.add("stale");
    if (error.status !== 401) announce(error.message, true);
  } finally { refreshing = false; }
}
function bindForm(id, action) {
  $(id).addEventListener("submit", async event => {
    event.preventDefault();
    const form = event.currentTarget, submit = form.querySelector("button[type=submit]");
    submit.disabled = true; announce("");
    try { await action(Object.fromEntries(new FormData(form)), form); }
    catch (error) { announce(error.message, true); }
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
  catch (error) { throw new Error(`Draft ${campaign.name} was saved but not published: ${error.message}`); }
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
async function uploadFile(file, row) {
  const label = node("span", `${file.name}: preparing`), progress = node("progress"); progress.max = 100; progress.value = 0;
  progress.setAttribute("aria-label", `Upload progress for ${file.name}`); row.replaceChildren(label, progress);
  try {
    const ticket = await post("/api/v1/agency/media/upload-ticket", { filename: file.name, size_bytes: file.size, declared_mime: file.type });
    label.textContent = `${file.name}: uploading`; await uploadBytes(ticket.presigned_upload_url, file, progress);
    label.textContent = `${file.name}: validating and processing`;
    await post("/api/v1/agency/media/finalize", { ticket_id: ticket.ticket_id });
    label.textContent = `${file.name}: ready`; progress.value = 100; await refresh();
  } catch (error) {
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
$("media-search").addEventListener("input", renderMedia);
$("refresh").addEventListener("click", refresh);
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
  refresh(); setInterval(() => { if (signedIn && !document.hidden) refresh(); }, 5000);
}
