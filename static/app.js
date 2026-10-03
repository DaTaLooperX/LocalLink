"use strict";
const $ = id => document.getElementById(id);
let me = null, cursor = 0, firstId = null, generation = 0, maxFile = 100 * 1024 * 1024;
let currentUpload = null, uploading = false, cancelQueue = false, noticeTimer;
const rendered = new Set();
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));
const initials = name => Array.from(name.trim()).slice(0, 2).join("").toUpperCase();
const bytes = value => value < 1024 ? `${value} B` : value < 1048576 ? `${(value / 1024).toFixed(1)} KB` : `${(value / 1048576).toFixed(1)} MB`;

async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json", "X-Local-Chat": "1"}, body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || "Request failed."); error.status = response.status; throw error;
  }
  return data;
}
function notice(message) {
  clearTimeout(noticeTimer); $("notice").textContent = message; $("notice").hidden = false;
  noticeTimer = setTimeout(() => { $("notice").hidden = true; }, 8000);
}
function status(online) {
  $("connection").classList.toggle("offline", !online);
  $("connection-text").textContent = online ? "Connected" : "Reconnecting";
}
function resetSession() {
  generation++; me = null; cancelQueue = true; currentUpload?.abort();
  $("my-name").textContent = "Not connected"; $("my-avatar").textContent = "?";
  $("people").replaceChildren(); $("people-count").textContent = "0";
  $("messages").replaceChildren(); rendered.clear(); cursor = 0; firstId = null;
  $("older").hidden = true; $("welcome").hidden = false;
  $("connection-text").textContent = "Not connected"; $("connection").classList.add("offline");
  $("sidebar").classList.remove("open"); $("menu").setAttribute("aria-expanded", "false");
  if (!$("join-dialog").open) $("join-dialog").showModal();
}
function renderPeople(people) {
  $("people-count").textContent = people.length;
  $("people").replaceChildren(...people.map(person => {
    const li = document.createElement("li"), avatar = document.createElement("span"), name = document.createElement("span"), dot = document.createElement("span");
    avatar.className = "avatar"; avatar.textContent = initials(person.name);
    name.className = "person-name"; name.textContent = person.name;
    if (person.id === me?.client_id) { const you = document.createElement("small"); you.textContent = "you"; name.append(you); }
    dot.className = "dot"; li.append(avatar, name, dot); return li;
  }));
}
function messageNode(message) {
  const mine = message.client_id === me?.client_id;
  const article = document.createElement("article"); article.className = "message" + (mine ? " mine" : "");
  const avatar = document.createElement("span"); avatar.className = "avatar"; avatar.textContent = initials(message.sender);
  const content = document.createElement("div"); content.className = "message-content";
  const meta = document.createElement("div"); meta.className = "message-meta";
  const name = document.createElement("strong"); name.textContent = mine ? "You" : message.sender;
  const time = document.createElement("time"), date = new Date(message.created * 1000);
  time.dateTime = date.toISOString(); time.title = date.toLocaleString();
  time.textContent = date.toLocaleDateString() === new Date().toLocaleDateString() ? date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) : date.toLocaleDateString([], {month: "short", day: "numeric"}) + " · " + date.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"});
  meta.append(name, time);
  const bubble = document.createElement("div"); bubble.className = "bubble";
  if (message.file_id) {
    const link = document.createElement("a"); link.className = "file-card"; link.href = "/files/" + encodeURIComponent(message.file_id); link.download = message.filename;
    const icon = document.createElement("span"); icon.className = "file-icon"; icon.textContent = "▤";
    const details = document.createElement("span"); details.className = "file-details";
    const filename = document.createElement("strong"); filename.textContent = message.filename;
    const size = document.createElement("small"); size.textContent = bytes(message.size) + " · Download file";
    const arrow = document.createElement("span"); arrow.className = "file-arrow"; arrow.textContent = "↓";
    details.append(filename, size); link.append(icon, details, arrow); bubble.append(link);
  } else { bubble.textContent = message.text; }
  content.append(meta, bubble); article.append(avatar, content); return article;
}
function renderMessages(messages, prepend = false) {
  const timeline = $("timeline"), nearBottom = timeline.scrollHeight - timeline.scrollTop - timeline.clientHeight < 130;
  const previousHeight = timeline.scrollHeight, nodes = [];
  for (const message of messages) {
    if (rendered.has(message.id)) continue;
    rendered.add(message.id); nodes.push(messageNode(message));
    firstId = firstId === null ? message.id : Math.min(firstId, message.id);
  }
  if (prepend) $("messages").prepend(...nodes); else $("messages").append(...nodes);
  $("welcome").hidden = rendered.size > 0;
  if (prepend) timeline.scrollTop += timeline.scrollHeight - previousHeight;
  else if (nearBottom || messages.some(m => m.client_id === me?.client_id)) timeline.scrollTop = timeline.scrollHeight;
}
async function poll(run) {
  let initialized = false;
  while (me && run === generation) {
    try {
      const result = await api(initialized ? `/api/messages?after=${cursor}` : "/api/messages");
      if (run !== generation) return;
      renderMessages(result.messages); renderPeople(result.people); status(true);
      for (const message of result.messages) cursor = Math.max(cursor, message.id);
      if (!initialized) { $("older").hidden = !result.has_more; $("timeline").scrollTop = $("timeline").scrollHeight; }
      initialized = true;
    } catch (error) {
      if (run !== generation) return;
      if (error.status === 401) { resetSession(); return; }
      status(false); await wait(2000);
    }
  }
}
function enterRoom(user) {
  me = user; cursor = 0; firstId = null; rendered.clear(); $("messages").replaceChildren();
  $("my-name").textContent = user.name; $("my-avatar").textContent = initials(user.name);
  $("join-dialog").close(); $("room-password").value = ""; $("join-error").textContent = "";
  try { localStorage.setItem("locallink-name", user.name); } catch {}
  status(true); poll(++generation); $("message-input").focus();
}
$("join-dialog").addEventListener("cancel", event => event.preventDefault());
$("join-form").addEventListener("submit", async event => {
  event.preventDefault(); $("join-button").disabled = true; $("join-error").textContent = "";
  try { enterRoom(await api("/api/join", {name: $("display-name").value.trim(), password: $("room-password").value})); }
  catch (error) { $("join-error").textContent = error.status ? error.message : "Can't reach the host. Check the server is running."; }
  finally { $("join-button").disabled = false; }
});
$("leave").addEventListener("click", async () => {
  try { await api("/api/logout", {}); resetSession(); }
  catch { notice("Couldn't leave the room. Check your connection and try again."); }
});
$("older").addEventListener("click", async () => {
  $("older").disabled = true; const run = generation;
  try { const result = await api(`/api/messages?before=${firstId}`); if (run !== generation) return; renderMessages(result.messages, true); $("older").hidden = !result.has_more; }
  catch (error) { notice(error.message); }
  finally { $("older").disabled = false; }
});
$("composer").addEventListener("submit", async event => {
  event.preventDefault(); const input = $("message-input"), text = input.value.trim();
  if (!text || !me || $("send").disabled) return;
  const run = generation; $("send").disabled = true;
  try {
    await api("/api/messages", {text});
    if (run === generation && input.value.trim() === text) { input.value = ""; input.style.height = "auto"; }
  } catch (error) { notice(error.status ? error.message : "Connection lost. Check the room before resending; your message may have arrived."); if (error.status === 401) resetSession(); }
  finally { $("send").disabled = false; input.focus(); }
});
$("message-input").addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && !matchMedia("(pointer: coarse)").matches) { event.preventDefault(); $("composer").requestSubmit(); }
});
$("message-input").addEventListener("input", event => { event.target.style.height = "auto"; event.target.style.height = Math.min(event.target.scrollHeight, 130) + "px"; });
$("attach").addEventListener("click", () => $("file-input").click());
$("file-input").addEventListener("change", event => { uploadFiles([...event.target.files]); event.target.value = ""; });
$("cancel-upload").addEventListener("click", () => { cancelQueue = true; currentUpload?.abort(); });
async function uploadFiles(files) {
  if (!me || !files.length) return;
  if (uploading) { notice("Wait for the current upload to finish, or cancel it first."); return; }
  uploading = true; cancelQueue = false; $("attach").disabled = true;
  try {
    for (let index = 0; index < files.length; index++) {
      if (cancelQueue || !me) break;
      const file = files[index];
      if (file.size > maxFile) { notice(`${file.name} exceeds the ${bytes(maxFile)} file limit.`); continue; }
      $("upload-panel").hidden = false; $("upload-progress").value = 0;
      $("upload-label").textContent = `${index + 1}/${files.length} · ${file.name}`;
      try {
        await new Promise((resolve, reject) => {
          const xhr = currentUpload = new XMLHttpRequest();
          xhr.open("POST", "/api/files?name=" + encodeURIComponent(file.name));
          xhr.setRequestHeader("X-Local-Chat", "1"); xhr.setRequestHeader("Content-Type", "application/octet-stream");
          xhr.upload.onprogress = e => { if (e.lengthComputable) $("upload-progress").value = e.loaded / e.total * 100; };
          xhr.onload = () => { if (xhr.status >= 200 && xhr.status < 300) resolve(); else { let error = "Upload failed."; try { error = JSON.parse(xhr.responseText).error || error; } catch {} if (xhr.status === 401) resetSession(); reject(new Error(error)); } };
          xhr.onerror = () => reject(new Error("Connection lost. Check the room before uploading again; the file may have arrived."));
          xhr.onabort = () => reject(new Error("Upload cancelled. Any files already shared remain in the room."));
          xhr.send(file);
        });
      } catch (error) { notice(error.message); break; }
    }
  } finally { currentUpload = null; uploading = false; $("attach").disabled = false; $("upload-panel").hidden = true; }
}
let dragDepth = 0;
document.addEventListener("dragenter", event => { if (me && event.dataTransfer.types.includes("Files")) { event.preventDefault(); dragDepth++; $("drop-overlay").hidden = false; } });
document.addEventListener("dragover", event => { if (event.dataTransfer.types.includes("Files")) event.preventDefault(); });
document.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; $("drop-overlay").hidden = true; } });
document.addEventListener("drop", event => { event.preventDefault(); dragDepth = 0; $("drop-overlay").hidden = true; uploadFiles([...event.dataTransfer.files]); });
$("menu").addEventListener("click", () => { const open = $("sidebar").classList.toggle("open"); $("menu").setAttribute("aria-expanded", String(open)); });
const address = location.origin;
$("room-address").textContent = address;
$("address-hint").hidden = !["localhost", "127.0.0.1", "0.0.0.0"].includes(location.hostname);
$("copy-address").addEventListener("click", async () => {
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(address);
    else {
      const input = document.createElement("textarea"); input.value = address; document.body.append(input); input.select();
      const copied = document.execCommand("copy"); input.remove(); if (!copied) throw new Error();
    }
    notice("Room address copied. Other devices need the host's local IP, not localhost.");
  } catch { notice("Copy the address shown in the room details."); }
});
async function boot() {
  if (matchMedia("(pointer: coarse)").matches) $("send-hint").textContent = "Tap ↑ to send · Enter for a new line";
  try { $("display-name").value = localStorage.getItem("locallink-name") || ""; } catch {}
  try {
    const config = await api("/api/config"); maxFile = config.max_file_bytes;
    $("password-field").hidden = !config.password_required; $("room-password").required = config.password_required;
    $("file-limit").textContent = `Drop files here · Up to ${bytes(maxFile)} each`;
    try { enterRoom(await api("/api/me")); } catch (error) { if (error.status === 401) resetSession(); else throw error; }
  } catch {
    resetSession(); $("join-error").textContent = "Can't reach the host. Check the server, then refresh this page.";
  }
}
boot();
