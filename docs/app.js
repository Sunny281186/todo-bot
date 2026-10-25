// Meine To-Dos – kleine Web-App ohne Server.
// Daten liegen lokal (localStorage) und werden mit einer geheimen GitHub-Gist (todos.json) abgeglichen.
// Dieselbe Datei liest der Telegram-Bot (bot.py) und schickt daraus die Erinnerungen.

// Gleiche Kategorien wie im Bot (bot.py)
const CATEGORIES = [
  { id: "sunny", name: "Sunny", emoji: "🎀", area: "privat" },
  { id: "franny", name: "Franny", emoji: "🩷", area: "privat" },
  { id: "slb", name: "School-Life-Balance", emoji: "🎓", area: "business" },
  { id: "miller", name: "Michelle Miller", emoji: "🏚️", area: "business" },
  { id: "wagner", name: "Markus Wagner", emoji: "🏡", area: "business" },
  { id: "falk", name: "Stefan Falk", emoji: "💼", area: "business" },
];
const AREAS = [
  { id: "all", name: "Alle" },
  { id: "privat", name: "Privat" },
  { id: "business", name: "Business" },
];
const INBOX = { id: null, name: "Eingang", emoji: "📥" };
const FILE = "todos.json";
const GH = "https://api.github.com";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const catOf = (id) => CATEGORIES.find((c) => c.id === id) || INBOX;

// --- Zustand ------------------------------------------------------------------
function readLS(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function writeLS(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
}
let data = readLS("todo-data", { version: 1, todos: [] });
let cfg = readLS("todo-cfg", { token: "", gistId: "", local: false });
let view = readLS("todo-view", { area: "all", cat: "" });
let showDone = false;
let editing = null;

const visible = () => data.todos.filter((t) => !t.deleted);

// --- Datum & Erinnerung -------------------------------------------------------
function dueDate(due) {
  if (!due) return null;
  return new Date(due.length === 10 ? due + "T09:00" : due); // ohne Offset = lokale Zeit
}
const EVENING = 19; // „Am Vorabend“ = Vortag 19 Uhr (wie im Bot)
function remindAtOf(t) {
  if (!t.due || t.remind === null || t.remind === undefined) return null;
  if (t.remind === "abend") {
    const d = dueDate(t.due);
    d.setDate(d.getDate() - 1);
    d.setHours(EVENING, 0, 0, 0);
    return d.toISOString();
  }
  return new Date(dueDate(t.due).getTime() - t.remind * 60000).toISOString();
}
function startOfDay(d) { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; }
function fmtDue(due) {
  const d = dueDate(due);
  const today = startOfDay(new Date());
  const days = Math.round((startOfDay(d) - today) / 86400000);
  let day = days === 0 ? "Heute" : days === 1 ? "Morgen" : days === -1 ? "Gestern"
    : d.toLocaleDateString("de-DE", { weekday: "short", day: "numeric", month: "numeric" });
  if (Math.abs(days) > 180) day = d.toLocaleDateString("de-DE");
  return due.length === 10 ? day : `${day}, ${d.toLocaleTimeString("de-DE", { hour: "2-digit", minute: "2-digit" })}`;
}
function isLate(t) {
  if (!t.due || t.done) return false;
  if (t.due.length === 10) return startOfDay(dueDate(t.due)) < startOfDay(new Date());
  return dueDate(t.due) < new Date();
}
function bucket(t) {
  if (!t.due) return "nodate";
  if (isLate(t)) return "late";
  const days = Math.round((startOfDay(dueDate(t.due)) - startOfDay(new Date())) / 86400000);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days < 7) return "week";
  return "later";
}
const BUCKETS = [
  ["late", "Überfällig"], ["today", "Heute"], ["tomorrow", "Morgen"],
  ["week", "Diese Woche"], ["later", "Später"], ["nodate", "Ohne Datum"],
];

// --- Anzeige ------------------------------------------------------------------
function inView(t) {
  if (view.cat) return (t.cat || "") === view.cat;
  if (view.area === "all") return true;
  return catOf(t.cat).area === view.area;
}

function render() {
  writeLS("todo-view", view);
  const todos = visible();
  const open = todos.filter((t) => !t.done);

  $("#areas").innerHTML = AREAS.map((a) =>
    `<button data-area="${a.id}" class="${view.area === a.id && !view.cat ? "on" : ""}">${a.name}</button>`).join("");

  const cats = CATEGORIES.filter((c) => view.area === "all" || c.area === view.area);
  const inboxCount = open.filter((t) => !t.cat).length;
  $("#cats").innerHTML = cats.map((c) => {
    const n = open.filter((t) => t.cat === c.id).length;
    return `<button class="chip ${view.cat === c.id ? "on" : ""}" data-cat="${c.id}">${c.emoji} ${esc(c.name)}${n ? `<span class="n">${n}</span>` : ""}</button>`;
  }).join("") + (inboxCount ? `<button class="chip ${view.cat === "inbox" ? "on" : ""}" data-cat="inbox">📥 Eingang<span class="n">${inboxCount}</span></button>` : "");

  const shown = todos.filter((t) => view.cat === "inbox" ? !t.cat : inView(t));
  const shownOpen = shown.filter((t) => !t.done)
    .sort((a, b) => (a.due ? dueDate(a.due) : Infinity) - (b.due ? dueDate(b.due) : Infinity) || a.created - b.created);
  const shownDone = shown.filter((t) => t.done).sort((a, b) => b.updated - a.updated);

  let html = "";
  for (const [key, label] of BUCKETS) {
    const items = shownOpen.filter((t) => bucket(t) === key);
    if (items.length) html += `<section class="group ${key}"><h3>${label}</h3>${items.map(itemHtml).join("")}</section>`;
  }
  if (!shownOpen.length) html += `<div class="empty">✨ Alles erledigt hier.<br>Tippe auf + für ein neues To-Do.</div>`;
  if (shownDone.length) {
    html += `<button class="more" data-toggle-done>${showDone ? "Erledigte ausblenden" : `Erledigte anzeigen (${shownDone.length})`}</button>`;
    if (showDone) html += `<section class="group"><h3>Erledigt</h3>${shownDone.slice(0, 50).map(itemHtml).join("")}</section>`;
  }
  $("#list").innerHTML = html;
}

function itemHtml(t) {
  const c = catOf(t.cat);
  const meta = [];
  if (!view.cat || view.cat === "inbox") meta.push(`<span>${c.emoji} ${esc(c.name)}</span>`);
  if (t.due) meta.push(`<span class="${isLate(t) ? "late" : ""}">${t.remind !== null && t.remind !== undefined ? "🔔" : "📅"} ${fmtDue(t.due)}</span>`);
  if (t.notes) meta.push(`<span>📝</span>`);
  return `<div class="item ${t.done ? "done" : ""}" data-id="${esc(t.id)}">
    <button class="check" data-check aria-label="Erledigt">${t.done ? "✓" : ""}</button>
    <div class="body" data-edit><div class="t">${esc(t.title)}</div>${meta.length ? `<div class="meta">${meta.join("")}</div>` : ""}</div>
  </div>`;
}

// --- Bearbeiten ---------------------------------------------------------------
function openTodo(t) {
  editing = t;
  const defCat = t?.cat ?? (view.cat && view.cat !== "inbox" ? view.cat
    : view.area !== "all" ? CATEGORIES.find((c) => c.area === view.area).id : "sunny");
  $("#todoHeading").textContent = t ? "To-Do bearbeiten" : "Neues To-Do";
  $("#fTitle").value = t?.title || "";
  $("#fDate").value = t?.due ? t.due.slice(0, 10) : "";
  $("#fTime").value = t?.due && t.due.length > 10 ? t.due.slice(11, 16) : "";
  $("#fRemind").value = t?.remind ?? "";
  $("#fNotes").value = t?.notes || "";
  $("#btnDelete").style.visibility = t ? "visible" : "hidden";
  let pick = "";
  for (const area of ["privat", "business"]) {
    pick += `<div class="area">${area === "privat" ? "Privat" : "Business"}</div>`;
    pick += CATEGORIES.filter((c) => c.area === area).map((c) =>
      `<button type="button" class="chip ${c.id === defCat ? "on" : ""}" data-pick="${c.id}">${c.emoji} ${esc(c.name)}</button>`).join("");
  }
  $("#fCats").innerHTML = pick;
  updateRemindHint();
  $("#dlgTodo").showModal();
  if (!t) $("#fTitle").focus();
}

function pickedCat() {
  return $("#fCats .chip.on")?.dataset.pick || null;
}

function updateRemindHint() {
  const date = $("#fDate").value, remind = $("#fRemind").value;
  let hint = "";
  if (remind !== "" && !date) hint = "Für eine Erinnerung brauchst du ein Datum.";
  else if (remind !== "") hint = cfg.gistId ? "Die Erinnerung kommt per Telegram (± ein paar Minuten)."
    : "Erinnerungen per Telegram gehen erst, wenn die App verbunden ist (⚙️).";
  else if (date && !$("#fTime").value) hint = "Ohne Uhrzeit gilt 9:00 Uhr.";
  $("#remindHint").textContent = hint;
}

function saveForm() {
  const title = $("#fTitle").value.trim();
  if (!title) return;
  const date = $("#fDate").value, time = $("#fTime").value;
  const due = date ? (time ? `${date}T${time}` : date) : null;
  const r = $("#fRemind").value;
  const remind = r === "" || !due ? null : r === "abend" ? "abend" : Number(r);
  // per ID nachschlagen: ein Abgleich im Hintergrund kann data inzwischen ersetzt haben
  const old = editing && data.todos.find((x) => x.id === editing.id);
  const t = old || { id: newId(), created: Date.now(), done: false, reminded: false };
  const remindAt = remindAtOf({ due, remind });
  if (remindAt !== t.remindAt) t.reminded = !!remindAt && new Date(remindAt) < new Date(); // nichts Vergangenes nachschicken
  Object.assign(t, { title, cat: pickedCat(), due, remind, remindAt, notes: $("#fNotes").value.trim(), updated: Date.now() });
  delete t.tgmsg;
  if (!old) data.todos.push(t);
  changed();
}

function newId() {
  const b = new Uint8Array(5);
  crypto.getRandomValues(b);
  return [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
}

function changed() {
  writeLS("todo-data", data);
  render();
  schedulePush();
}

// --- Abgleich mit GitHub-Gist --------------------------------------------------
function setSync(state, title) {
  const el = $("#sync");
  el.className = "sync " + state;
  el.title = title;
}

async function gh(path, opts = {}) {
  const r = await fetch(GH + path, {
    ...opts,
    cache: "no-store",
    headers: { Authorization: `Bearer ${cfg.token}`, Accept: "application/vnd.github+json", ...(opts.headers || {}) },
  });
  if (!r.ok) throw new Error(`GitHub ${r.status}`);
  return r.json();
}

async function fetchRemote() {
  const g = await gh(`/gists/${cfg.gistId}`);
  const f = g.files[FILE];
  if (!f) return { version: 1, todos: [] };
  const text = f.truncated ? await (await fetch(f.raw_url, { cache: "no-store" })).text() : f.content;
  return JSON.parse(text || "{}");
}

// Neuere Änderung gewinnt (pro To-Do), gelöschte bleiben als Markierung erhalten.
function merge(a, b) {
  const map = new Map();
  for (const t of [...(a.todos || []), ...(b.todos || [])]) {
    const cur = map.get(t.id);
    if (!cur || (t.updated || 0) > (cur.updated || 0)) map.set(t.id, t);
  }
  const month = Date.now() - 30 * 86400000;
  return { version: 1, todos: [...map.values()].filter((t) => !(t.deleted && t.updated < month)) };
}

let busy = false, again = false, pushTimer = null;

function schedulePush() {
  if (!cfg.gistId) return;
  clearTimeout(pushTimer);
  pushTimer = setTimeout(() => sync(true), 700);
}

async function sync(push) {
  if (!cfg.gistId) { setSync("local", "Nur auf diesem Gerät gespeichert"); return; }
  if (busy) { again = again || push; return; }
  busy = true;
  setSync("busy", "Synchronisiere …");
  try {
    const remote = await fetchRemote();
    const merged = merge(remote, data);
    const differs = JSON.stringify(merged.todos.slice().sort(byId)) !== JSON.stringify((remote.todos || []).slice().sort(byId));
    data = merged;
    writeLS("todo-data", data);
    if (push && differs) {
      await gh(`/gists/${cfg.gistId}`, {
        method: "PATCH",
        body: JSON.stringify({ files: { [FILE]: { content: JSON.stringify(data, null, 1) } } }),
      });
    }
    setSync("ok", "Synchronisiert " + new Date().toLocaleTimeString("de-DE"));
    render();
  } catch (e) {
    setSync("err", "Nicht synchronisiert: " + e.message);
  } finally {
    busy = false;
    if (again) { again = false; sync(true); }
  }
}
const byId = (a, b) => (a.id < b.id ? -1 : 1);

async function connect(token, gistId) {
  cfg = { token, gistId: "", local: false };
  if (!gistId) {
    // vorhandene To-Do-Gist suchen (z. B. vom anderen Handy), sonst neu anlegen
    for (let page = 1; page <= 5 && !gistId; page++) {
      const list = await gh(`/gists?per_page=100&page=${page}`);
      gistId = list.find((g) => g.files[FILE] && /To-Dos/.test(g.description || ""))?.id || "";
      if (list.length < 100) break;
    }
  }
  if (!gistId) {
    const g = await gh("/gists", {
      method: "POST",
      body: JSON.stringify({
        description: "Meine To-Dos (App-Daten, nicht löschen)",
        public: false,
        files: { [FILE]: { content: JSON.stringify(data, null, 1) } },
      }),
    });
    gistId = g.id;
  } else {
    await gh(`/gists/${gistId}`); // prüft Token + ID
  }
  cfg.gistId = gistId;
  writeLS("todo-cfg", cfg);
}

function openSettings() {
  $("#sToken").value = cfg.token || "";
  $("#sGist").value = cfg.gistId || "";
  $("#sStatus").innerHTML = cfg.gistId
    ? `Verbunden ✅<br>Gist-ID für den Bot (Secret <b>TODO_GIST_ID</b>): <code>${esc(cfg.gistId)}</code>`
    : "Noch nicht verbunden.";
  $("#dlgSettings").showModal();
}

// --- Ereignisse ---------------------------------------------------------------
$("#areas").addEventListener("click", (e) => {
  const b = e.target.closest("[data-area]");
  if (b) { view = { area: b.dataset.area, cat: "" }; render(); }
});
$("#cats").addEventListener("click", (e) => {
  const b = e.target.closest("[data-cat]");
  if (b) { view.cat = view.cat === b.dataset.cat ? "" : b.dataset.cat; render(); }
});
$("#list").addEventListener("click", (e) => {
  if (e.target.closest("[data-toggle-done]")) { showDone = !showDone; render(); return; }
  const row = e.target.closest(".item");
  if (!row) return;
  const t = data.todos.find((x) => x.id === row.dataset.id);
  if (e.target.closest("[data-check]")) {
    t.done = !t.done;
    t.updated = Date.now();
    changed();
  } else if (e.target.closest("[data-edit]")) {
    openTodo(t);
  }
});
$("#btnAdd").addEventListener("click", () => openTodo(null));
$("#fCats").addEventListener("click", (e) => {
  const b = e.target.closest("[data-pick]");
  if (!b) return;
  $("#fCats").querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", x === b));
});
["#fDate", "#fTime", "#fRemind"].forEach((s) => $(s).addEventListener("input", updateRemindHint));
$("#fDate").addEventListener("change", () => {
  if ($("#fDate").value && $("#fRemind").value === "" && !editing) $("#fRemind").value = "0";
  updateRemindHint();
});
$("#todoForm").addEventListener("submit", saveForm);
$("#btnCancel").addEventListener("click", () => $("#dlgTodo").close());
$("#btnDelete").addEventListener("click", () => {
  const t = editing && data.todos.find((x) => x.id === editing.id);
  if (!t || !confirm("Dieses To-Do löschen?")) return;
  Object.assign(t, { deleted: true, updated: Date.now() });
  $("#dlgTodo").close();
  changed();
});
$("#dlgTodo").addEventListener("close", () => { editing = null; });

$("#btnSettings").addEventListener("click", openSettings);
$("#btnLocal").addEventListener("click", () => {
  cfg.local = true;
  writeLS("todo-cfg", cfg);
  $("#dlgSettings").close();
  sync(false);
});
$("#settingsForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const token = $("#sToken").value.trim();
  if (!token) { $("#sStatus").textContent = "Bitte einen Token eintragen."; return; }
  $("#sStatus").textContent = "Verbinde …";
  try {
    await connect(token, $("#sGist").value.trim());
    await sync(true);
    openSettings();
  } catch (err) {
    $("#sStatus").textContent = "Das hat nicht geklappt (" + err.message + "). Hat der Token das Recht „Gists: Lesen und Schreiben“?";
  }
});

document.addEventListener("visibilitychange", () => { if (!document.hidden) sync(false); });
setInterval(() => { if (!document.hidden) sync(false); }, 60000);
setInterval(render, 5 * 60000); // „Heute“/„Überfällig“ aktuell halten

if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});

render();
if (!cfg.gistId && !cfg.local) openSettings();
else sync(false);
