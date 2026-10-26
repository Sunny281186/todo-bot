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
  { id: "falk", name: "Stefan Falk", emoji: "🌐", area: "business" },
];
const AREAS = [
  { id: "all", name: "Alle" },
  { id: "privat", name: "Privat" },
  { id: "business", name: "Business" },
];
const INBOX = { id: null, name: "Eingang", emoji: "📥" };
// Spalten des Kanban-Boards
const STATUSES = [
  { id: "new", emoji: "🆕", name: "New" },
  { id: "todo", emoji: "📋", name: "To-Do" },
  { id: "doing", emoji: "🔨", name: "In Bearbeitung" },
  { id: "wait", emoji: "⏳", name: "Wait" },
  { id: "done", emoji: "✅", name: "Erledigt" },
];
const FILE = "todos.json"; // schreibt nur die App
const BOT_FILE = "todos-bot.json"; // schreibt nur der Bot – so überschreibt keiner die Änderungen des anderen
const GH = "https://api.github.com";

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const catOf = (id) => CATEGORIES.find((c) => c.id === id) || INBOX;
const statusOf = (t) => t.status || (t.done ? "done" : "new"); // ältere To-Dos haben noch keinen Status
function setStatus(t, status) {
  Object.assign(t, { status, done: status === "done", updated: Date.now() });
}

// --- Zustand ------------------------------------------------------------------
function readLS(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function writeLS(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch {}
}
let data = readLS("todo-data", { version: 1, todos: [] });
let cfg = readLS("todo-cfg", { token: "", gistId: "", local: false });

// Verbindung aus der Adresse (#verbindung=…) übernehmen. Auf dem iPhone hat die App auf dem Home-Bildschirm
// einen eigenen Speicher ohne Token – so bringt das Symbol die Verbindung bei jedem Start selbst mit.
// Was hinter # steht, wird nie an einen Server geschickt.
const SETUP_KEY = "verbindung";
function setupFromUrl() {
  const m = location.hash.match(new RegExp(`${SETUP_KEY}=([\\w-]+)`));
  if (!m) return;
  try {
    const { t, g } = JSON.parse(atob(m[1].replace(/-/g, "+").replace(/_/g, "/")));
    if (t && g && (t !== cfg.token || g !== cfg.gistId)) {
      cfg = { token: t, gistId: g, local: false };
      writeLS("todo-cfg", cfg);
    }
  } catch {}
}
function setupUrl() {
  const code = btoa(JSON.stringify({ t: cfg.token, g: cfg.gistId })).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  return `${location.origin}${location.pathname}#${SETUP_KEY}=${code}`;
}
setupFromUrl();
let view = { mode: "list", ...readLS("todo-view", { area: "all", cat: "" }) };
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

  document.body.classList.toggle("board-mode", view.mode === "board");
  $("#btnMode").textContent = view.mode === "board" ? "☰ Liste" : "🗂️ Board";
  $("#areas").innerHTML = AREAS.map((a) =>
    `<button data-area="${a.id}" class="${view.area === a.id && !view.cat ? "on" : ""}">${a.name}</button>`).join("");

  const cats = CATEGORIES.filter((c) => view.area === "all" || c.area === view.area);
  const inboxCount = open.filter((t) => !t.cat).length;
  $("#cats").innerHTML = cats.map((c) => {
    const n = open.filter((t) => t.cat === c.id).length;
    return `<button class="chip ${view.cat === c.id ? "on" : ""}" data-cat="${c.id}">${c.emoji} ${esc(c.name)}${n ? `<span class="n">${n}</span>` : ""}</button>`;
  }).join("") + (inboxCount ? `<button class="chip ${view.cat === "inbox" ? "on" : ""}" data-cat="inbox">📥 Eingang<span class="n">${inboxCount}</span></button>` : "");

  const shown = todos.filter((t) => view.cat === "inbox" ? !t.cat : inView(t));
  if (view.mode === "board") { renderBoard(shown); return; }
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

// Kanban: eine Spalte pro Status. Mit Kunden-Filter = Board dieses Kunden, sonst Gesamtübersicht.
function renderBoard(shown) {
  const byDue = (a, b) => (a.due ? dueDate(a.due) : Infinity) - (b.due ? dueDate(b.due) : Infinity) || a.created - b.created;
  $("#list").innerHTML = `<div class="board">${STATUSES.map((s) => {
    let items = shown.filter((t) => statusOf(t) === s.id);
    items = s.id === "done" ? items.sort((a, b) => b.updated - a.updated).slice(0, 30) : items.sort(byDue);
    return `<section class="col" data-status="${s.id}">
      <h3>${s.emoji} ${s.name}<span class="n">${items.length}</span></h3>
      <div class="cards">${items.map(cardHtml).join("")}</div>
      <button class="add-in" data-add="${s.id}">+ Hinzufügen</button>
    </section>`;
  }).join("")}</div>`;
}

function cardHtml(t) {
  const c = catOf(t.cat);
  const meta = [];
  if (!view.cat || view.cat === "inbox") meta.push(`<span>${esc(c.name)}</span>`);
  if (t.due) meta.push(`<span class="${isLate(t) ? "late" : ""}">${t.remind !== null && t.remind !== undefined ? "🔔" : "📅"} ${fmtDue(t.due)}</span>`);
  if (t.notes) meta.push(`<span>📝</span>`);
  return `<div class="card ${t.done ? "done" : ""}" draggable="true" data-id="${esc(t.id)}">
    <div class="t"><span class="cat-emoji">${c.emoji}</span> ${esc(t.title)}</div>${meta.length ? `<div class="meta">${meta.join("")}</div>` : ""}
  </div>`;
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
function openTodo(t, status) {
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
  const st = t ? statusOf(t) : status || "new";
  $("#fStatus").innerHTML = STATUSES.map((s) =>
    `<button type="button" class="chip ${s.id === st ? "on" : ""}" data-status="${s.id}">${s.emoji} ${s.name}</button>`).join("");
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
  Object.assign(t, { title, cat: pickedCat(), due, remind, remindAt, notes: $("#fNotes").value.trim() });
  setStatus(t, $("#fStatus .chip.on")?.dataset.status || statusOf(t));
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
  const read = async (f) => {
    if (!f) return { version: 1, todos: [] };
    const text = f.truncated ? await (await fetch(f.raw_url, { cache: "no-store" })).text() : f.content;
    return JSON.parse(text || "{}");
  };
  return { own: await read(g.files[FILE]), bot: await read(g.files[BOT_FILE]) };
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
    const { own: remote, bot } = await fetchRemote();
    const merged = merge(merge(remote, bot), data);
    // Zeitzone dieses Geräts melden (auf Reisen), damit der Bot zur richtigen Ortszeit erinnert
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    merged.tz = tz;
    if (remote.tz !== tz) {
      for (const t of merged.todos) { // Erinnerungen auf die neue Ortszeit umrechnen
        if (t.done || t.deleted || t.reminded || !t.due || t.remind === null || t.remind === undefined) continue;
        const at = remindAtOf(t);
        if (at !== t.remindAt) Object.assign(t, { remindAt: at, updated: Date.now() });
      }
    }
    const differs = remote.tz !== tz ||
      JSON.stringify(merged.todos.slice().sort(byId)) !== JSON.stringify((remote.todos || []).slice().sort(byId));
    data = merged;
    writeLS("todo-data", data);
    if ((push || remote.tz !== tz) && differs) {
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
  showSettingsStatus();
  if (!$("#dlgSettings").open) $("#dlgSettings").showModal();
}

function showSettingsStatus() {
  $("#sStatus").innerHTML = cfg.gistId
    ? `Verbunden ✅<br>Gist-ID für den Bot (Secret <b>TODO_GIST_ID</b>): <code>${esc(cfg.gistId)}</code>`
    : "Noch nicht verbunden.";
  // verbunden: nur noch „Schließen“ nötig; „Verbinden“ bleibt zum Wechseln des Tokens
  $("#btnLocal").hidden = !!cfg.gistId;
  $("#homeSetup").hidden = !cfg.gistId;
  $("#btnConnect").textContent = cfg.gistId ? "Neu verbinden" : "Verbinden";
}

// --- Ereignisse ---------------------------------------------------------------
$("#areas").addEventListener("click", (e) => {
  const b = e.target.closest("[data-area]");
  if (b) { view = { ...view, area: b.dataset.area, cat: "" }; render(); }
});
$("#cats").addEventListener("click", (e) => {
  const b = e.target.closest("[data-cat]");
  if (b) { view.cat = view.cat === b.dataset.cat ? "" : b.dataset.cat; render(); }
});
$("#list").addEventListener("click", (e) => {
  if (e.target.closest("[data-toggle-done]")) { showDone = !showDone; render(); return; }
  const add = e.target.closest("[data-add]");
  if (add) { openTodo(null, add.dataset.add); return; }
  const card = e.target.closest(".card");
  if (card) { openTodo(data.todos.find((x) => x.id === card.dataset.id)); return; }
  const row = e.target.closest(".item");
  if (!row) return;
  const t = data.todos.find((x) => x.id === row.dataset.id);
  if (e.target.closest("[data-check]")) {
    setStatus(t, t.done ? "todo" : "done");
    changed();
  } else if (e.target.closest("[data-edit]")) {
    openTodo(t);
  }
});
$("#btnAdd").addEventListener("click", () => openTodo(null));
$("#btnMode").addEventListener("click", () => { view.mode = view.mode === "board" ? "list" : "board"; render(); });
$("#fStatus").addEventListener("click", (e) => {
  const b = e.target.closest("[data-status]");
  if (b) $("#fStatus").querySelectorAll(".chip").forEach((x) => x.classList.toggle("on", x === b));
});

// Karten am Laptop per Maus in eine andere Spalte ziehen
$("#list").addEventListener("dragstart", (e) => {
  const card = e.target.closest(".card");
  if (card) { e.dataTransfer.setData("text/plain", card.dataset.id); card.classList.add("dragging"); }
});
$("#list").addEventListener("dragend", (e) => e.target.closest(".card")?.classList.remove("dragging"));
$("#list").addEventListener("dragover", (e) => {
  const col = e.target.closest(".col");
  if (!col) return;
  e.preventDefault();
  document.querySelectorAll(".col.over").forEach((c) => c !== col && c.classList.remove("over"));
  col.classList.add("over");
});
$("#list").addEventListener("dragleave", (e) => {
  const col = e.target.closest(".col");
  if (col && !col.contains(e.relatedTarget)) col.classList.remove("over");
});
$("#list").addEventListener("drop", (e) => {
  const col = e.target.closest(".col");
  if (!col) return;
  e.preventDefault();
  col.classList.remove("over");
  const t = data.todos.find((x) => x.id === e.dataTransfer.getData("text/plain"));
  if (t && statusOf(t) !== col.dataset.status) { setStatus(t, col.dataset.status); changed(); }
});
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
$("#btnCloseSettings").addEventListener("click", () => $("#dlgSettings").close());
$("#btnHomeSetup").addEventListener("click", () => {
  history.replaceState(null, "", setupUrl());
  $("#homeHint").hidden = false;
});
// Klick neben das Fenster schließt es
for (const dlg of [$("#dlgSettings"), $("#dlgTodo")]) {
  dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
}
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
    showSettingsStatus();
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
