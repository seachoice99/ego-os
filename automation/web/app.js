"use strict";

const POLL_MS = 3000;
let offline = false;
let lastEventCount = 0;

function setOffline(isOffline) {
  offline = isOffline;
  document.getElementById("offline-banner").classList.toggle("hidden", !isOffline);
}

async function api(path, options) {
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options && options.headers) },
  });
  let body = null;
  try { body = await res.json(); } catch { /* no body */ }
  if (!res.ok) throw { status: res.status, body };
  return body;
}

function fmtDuration(ms) {
  if (!ms && ms !== 0) return "—";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} с`;
  const m = Math.floor(s / 60);
  return `${m} мин ${s % 60} с`;
}

function fmtTime(iso) {
  if (!iso) return "—";
  try { return new Date(iso).toLocaleString("ru-RU"); } catch { return iso; }
}

// --- confirmation modal --------------------------------------------------

function confirmAction(text) {
  return new Promise((resolve) => {
    const modal = document.getElementById("confirm-modal");
    document.getElementById("confirm-text").textContent = text;
    modal.classList.remove("hidden");
    const cleanup = (result) => { modal.classList.add("hidden"); resolve(result); };
    document.getElementById("confirm-ok").onclick = () => cleanup(true);
    document.getElementById("confirm-cancel").onclick = () => cleanup(false);
  });
}

// --- top status bar -------------------------------------------------------

async function refreshStatus() {
  const status = await api("/api/status");
  const badge = document.getElementById("runner-badge");
  badge.textContent = status.runner_state;
  badge.className = `badge badge-${status.runner_state}`;

  const task = status.current_task;
  document.getElementById("current-task-line").textContent = task
    ? `${task.id} — ${task.title}`
    : "Задача не выполняется";
  document.getElementById("topbar-meta").textContent = [
    status.pid ? `PID ${status.pid}` : null,
    status.updated_at ? `обновлено: ${fmtTime(status.updated_at)}` : null,
    status.reason ? `причина: ${status.reason}` : null,
  ].filter(Boolean).join(" · ");

  document.getElementById("current-operation").textContent = task
    ? `${task.summary || "Выполняется без промежуточной сводки."}`
    : "Нет активной задачи.";
  document.getElementById("stage-progress").textContent = task ? `${task.sessions_count} сессия(й)` : "—";
  document.getElementById("last-commit").textContent = task && task.summary ? "см. журнал сессий" : "—";
  document.getElementById("limit-reset").textContent = task && task.retry_after ? fmtTime(task.retry_after) : "не установлено";

  document.getElementById("auth-state").textContent = status.runner_state === "authentication_required"
    ? "Доступ к Claude недоступен (подписка/API-ключ) — требуется ручное вмешательство."
    : "Проблем с доступом не обнаружено.";

  updateButtons(status.runner_state);
  return status;
}

function updateButtons(state) {
  const allowed = {
    start: state === "stopped" || state === "completed" || state === "failed",
    pause: state === "running" || state === "idle" || state === "starting",
    resume: state === "paused" || state === "pause_requested",
    stopStage: state === "running" || state === "idle" || state === "starting" || state === "pause_requested",
    emergency: state !== "stopped",
  };
  document.getElementById("btn-start").disabled = !allowed.start;
  document.getElementById("btn-pause").disabled = !allowed.pause;
  document.getElementById("btn-resume").disabled = !allowed.resume;
  document.getElementById("btn-stop-stage").disabled = !allowed.stopStage;
  document.getElementById("btn-emergency").disabled = !allowed.emergency;
}

// --- queue: casual grouped cards + technical detail -----------------------
//
// Server-side (runner_control.summarizeTask) already attaches group_key/
// group_name/group_casual_summary/display_summary per task -- this file
// only groups, sorts, and renders what it's given, it never re-derives a
// task's project from its id itself (that logic lives in exactly one
// place: automation/project_groups.js).

const ACTIONS_BY_STATUS = {
  ready: ["hold"],
  held: ["unhold"],
  failed: ["retry"],
  waiting_for_auth: ["retry"],
  interrupted: ["retry"],
  blocked: [],
  waiting_for_limit: [],
};

const NEEDS_ATTENTION_STATUSES = new Set(["blocked", "waiting_for_auth", "failed", "interrupted"]);
const PRIORITY_RANK = { P0: 0, P1: 1, P2: 2, P3: 3 };
const EXPANDED_STORAGE_KEY = "egoos.dashboard.expandedGroups";

function actionLabel(action) {
  return { hold: "Отложить", unhold: "Вернуть", retry: "Повторить" }[action] || action;
}

function rowActionsFor(task) {
  const actions = ACTIONS_BY_STATUS[task.status] || [];
  const buttons = actions.map((a) =>
    `<button class="btn btn-small" data-action="${a}" data-id="${task.id}">${actionLabel(a)}</button>`
  ).join(" ");
  const skip = ["ready", "held", "blocked", "waiting_for_limit", "waiting_for_auth"].includes(task.status)
    ? `<button class="btn btn-small" data-action="skip" data-id="${task.id}">Пропустить</button>` : "";
  const openLog = `<button class="btn btn-small" data-action="open-log" data-id="${task.id}">Лог</button>`;
  return `${buttons} ${skip} ${openLog}`;
}

function loadExpandedGroups() {
  try { return new Set(JSON.parse(localStorage.getItem(EXPANDED_STORAGE_KEY) || "[]")); } catch { return new Set(); }
}

function saveExpandedGroups(set) {
  try { localStorage.setItem(EXPANDED_STORAGE_KEY, JSON.stringify([...set])); } catch { /* storage unavailable -- not fatal */ }
}

let expandedGroups = loadExpandedGroups();
let currentGroups = []; // last rendered group order + per-group task order, used as the source of truth when a drag-and-drop submits a reorder

function taskSortKey(t) {
  return `${(PRIORITY_RANK[t.priority] ?? 99).toString().padStart(2, "0")}-${String(t.queue_order ?? 999999).padStart(8, "0")}-${t.id}`;
}

// Groups by the server-attached group_key -- never re-derives it from the
// task id client-side, so there is exactly one place that mapping lives.
function buildGroups(tasks) {
  const byKey = new Map();
  for (const t of tasks) {
    if (!byKey.has(t.group_key)) {
      byKey.set(t.group_key, { key: t.group_key, name: t.group_name, casual_summary: t.group_casual_summary, tasks: [] });
    }
    byKey.get(t.group_key).tasks.push(t);
  }
  const groups = [...byKey.values()];
  for (const g of groups) {
    g.tasks.sort((a, b) => taskSortKey(a).localeCompare(taskSortKey(b)));
    g.readyTasks = g.tasks.filter((t) => t.status === "ready");
    g.needsAttention = g.tasks.some((t) => NEEDS_ATTENTION_STATUSES.has(t.status));
    g.doneCount = g.tasks.filter((t) => t.status === "done").length;
    g.rank = g.readyTasks.length
      ? Math.min(...g.readyTasks.map((t) => (PRIORITY_RANK[t.priority] ?? 99) * 1e9 + (t.queue_order ?? 1e6)))
      : Infinity;
  }
  groups.sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name));
  return groups;
}

function statusCountsLabel(tasks) {
  const total = tasks.length;
  const done = tasks.filter((t) => t.status === "done").length;
  if (done === total) return `${total}/${total} выполнено`;
  const active = tasks.filter((t) => ["in_progress", "ready", "checkpointing"].includes(t.status)).length;
  return `${done}/${total} выполнено${active ? `, ${active} в очереди` : ""}`;
}

function renderTechnicalTable(tasks) {
  return `
    <table class="tech-table">
      <thead>
        <tr><th>ID</th><th>Название</th><th>Приоритет</th><th>Статус</th><th>Release</th><th>Owner</th><th>Причина блокировки</th><th>Действия</th></tr>
      </thead>
      <tbody>
        ${tasks.map((t) => `
          <tr class="task-row" draggable="${t.status === "ready"}" data-row-id="${t.id}" data-group="${t.group_key}">
            <td>${t.id}</td>
            <td>${t.title || ""}</td>
            <td>${t.priority}</td>
            <td><span class="status-pill status-${t.status}">${t.status}</span></td>
            <td>${t.release}</td>
            <td>${t.owner_approved ? "да" : "нет"}</td>
            <td>${t.blocked_reason || "—"}</td>
            <td class="row-actions">${rowActionsFor(t)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function renderGroupCard(group) {
  const expanded = expandedGroups.has(group.key);
  const attentionBadge = group.needsAttention ? `<span class="badge badge-authentication_required">нужно ваше внимание</span>` : "";
  return `
    <div class="group-card${group.needsAttention ? " group-card-attention" : ""}" draggable="true" data-group-card="${group.key}">
      <div class="group-card-header">
        <span class="drag-handle" title="Перетащите, чтобы изменить приоритет">⠿</span>
        <div class="group-card-title">
          <div class="group-name">${group.name}</div>
          <div class="muted group-casual">${group.casual_summary}</div>
        </div>
        <div class="group-card-meta">
          ${attentionBadge}
          <span class="muted">${statusCountsLabel(group.tasks)}</span>
          <button class="btn btn-small" data-toggle-group="${group.key}">${expanded ? "Свернуть" : "Технический список"}</button>
        </div>
      </div>
      ${expanded ? `<div class="group-card-body">${renderTechnicalTable(group.tasks)}</div>` : ""}
    </div>
  `;
}

async function refreshQueue() {
  const { tasks } = await api("/api/tasks");
  currentGroups = buildGroups(tasks);
  const container = document.getElementById("queue-groups");
  container.innerHTML = currentGroups.map(renderGroupCard).join("");
  wireGroupInteractions(container);
}

// Flattens the CURRENT on-screen group/task order into one ready-task-id
// list and submits it as the new global queue_order in a single call --
// deliberately never a narrow per-group submission, which would let two
// groups independently reuse the same small queue_order numbers and
// silently scramble the global order a previous group-level drag set up.
async function submitReorderFromCurrentGroups() {
  const order = currentGroups.flatMap((g) => g.readyTasks.map((t) => t.id));
  if (!order.length) return;
  try {
    await api("/api/tasks/reorder", { method: "POST", body: JSON.stringify({ order }) });
  } catch (e) {
    alert(`Не удалось сохранить новый порядок: ${(e.body && e.body.error) || e.status}`);
  }
  await refreshQueue();
}

function wireGroupInteractions(container) {
  container.querySelectorAll("[data-toggle-group]").forEach((btn) => {
    btn.onclick = () => {
      const key = btn.dataset.toggleGroup;
      if (expandedGroups.has(key)) expandedGroups.delete(key); else expandedGroups.add(key);
      saveExpandedGroups(expandedGroups);
      refreshQueue();
    };
  });
  container.querySelectorAll("[data-action]").forEach((btn) => {
    btn.addEventListener("click", () => handleRowAction(btn.dataset.action, btn.dataset.id));
  });
  wireGroupCardDragAndDrop(container);
  wireRowDragAndDrop(container);
}

// --- drag-and-drop: group cards (global priority) -------------------------

function wireGroupCardDragAndDrop(container) {
  let draggedKey = null;
  container.querySelectorAll("[data-group-card]").forEach((card) => {
    card.addEventListener("dragstart", (e) => {
      draggedKey = card.dataset.groupCard;
      e.dataTransfer.effectAllowed = "move";
    });
    card.addEventListener("dragover", (e) => {
      if (!draggedKey || draggedKey === card.dataset.groupCard) return;
      e.preventDefault();
      card.classList.add("drag-over");
    });
    card.addEventListener("dragleave", () => card.classList.remove("drag-over"));
    card.addEventListener("drop", (e) => {
      e.preventDefault();
      card.classList.remove("drag-over");
      const targetKey = card.dataset.groupCard;
      if (!draggedKey || draggedKey === targetKey) return;
      const fromIndex = currentGroups.findIndex((g) => g.key === draggedKey);
      const toIndex = currentGroups.findIndex((g) => g.key === targetKey);
      if (fromIndex < 0 || toIndex < 0) return;
      const [moved] = currentGroups.splice(fromIndex, 1);
      currentGroups.splice(toIndex, 0, moved);
      draggedKey = null;
      submitReorderFromCurrentGroups();
    });
  });
}

// --- drag-and-drop: rows inside one expanded group (local order) ---------

function wireRowDragAndDrop(container) {
  let draggedId = null, draggedGroupKey = null;
  container.querySelectorAll(".task-row[draggable='true']").forEach((row) => {
    row.addEventListener("dragstart", (e) => {
      draggedId = row.dataset.rowId;
      draggedGroupKey = row.dataset.group;
      e.dataTransfer.effectAllowed = "move";
      e.stopPropagation(); // never let this bubble into the group-card's own dragstart
    });
    row.addEventListener("dragover", (e) => {
      if (!draggedId || row.dataset.group !== draggedGroupKey || row.dataset.rowId === draggedId) return;
      e.preventDefault();
      e.stopPropagation();
      row.classList.add("drag-over");
    });
    row.addEventListener("dragleave", () => row.classList.remove("drag-over"));
    row.addEventListener("drop", (e) => {
      e.preventDefault();
      e.stopPropagation();
      row.classList.remove("drag-over");
      const targetId = row.dataset.rowId;
      if (!draggedId || draggedId === targetId || row.dataset.group !== draggedGroupKey) return;
      const group = currentGroups.find((g) => g.key === draggedGroupKey);
      if (!group) return;
      const fromIndex = group.readyTasks.findIndex((t) => t.id === draggedId);
      const toIndex = group.readyTasks.findIndex((t) => t.id === targetId);
      if (fromIndex < 0 || toIndex < 0) return;
      const [moved] = group.readyTasks.splice(fromIndex, 1);
      group.readyTasks.splice(toIndex, 0, moved);
      draggedId = null;
      submitReorderFromCurrentGroups();
    });
  });
}

async function handleRowAction(action, id) {
  if (action === "open-log") return openLatestLog(id);
  const dangerous = action === "skip" || action === "retry";
  if (dangerous) {
    const ok = await confirmAction(`Подтвердите действие «${actionLabel(action) || action}» для задачи ${id}.`);
    if (!ok) return;
  }
  try {
    await api(`/api/tasks/${encodeURIComponent(id)}/${action}`, { method: "POST", body: JSON.stringify({ confirm: dangerous }) });
    await refreshQueue();
  } catch (e) {
    alert(`Не удалось выполнить «${action}»: ${(e.body && e.body.error) || e.status}`);
  }
}

// --- limits / usage tracker ------------------------------------------------

function fmtUsd(n) {
  return typeof n === "number" ? `$${n.toFixed(4)}` : "—";
}

function fmtWindow(label, w) {
  if (!w || typeof w.remaining_percent !== "number") return "";
  const resets = w.resets_at ? `, сброс ${fmtTime(w.resets_at)}` : "";
  return `<dt>${label}</dt><dd>${w.remaining_percent}% remaining${resets}</dd>`;
}

// `rate_limits`, when present, comes from automation/codex_usage.js's real
// `codex app-server` snapshot (see automation/README.md) -- a genuinely
// different, richer data source than the session-cost fields below, which
// stay empty for Codex until a real Codex session ever runs (MED-02).
function renderExecutorUsage(label, u) {
  const rl = u && u.rate_limits;
  const hasSessionData = u && u.total_sessions > 0;
  if (!hasSessionData && !rl) {
    return `<div class="usage-card"><div class="usage-title">${label}</div><div class="muted">Нет данных — сессий ещё не было.</div></div>`;
  }
  const rateLimitBlock = rl ? `
    <dt>Статус лимитов</dt><dd>${rl.status}${rl.error ? ` (${rl.error})` : ""}</dd>
    ${fmtWindow("5ч окно", rl.primary)}
    ${fmtWindow("Недельное окно", rl.secondary)}
    <dt>Проверено</dt><dd>${fmtTime(rl.checked_at)}</dd>
  ` : "";
  const sessionBlock = hasSessionData ? `
    <dt>Сессий всего</dt><dd>${u.total_sessions}</dd>
    <dt>Стоимость всего</dt><dd>${fmtUsd(u.total_cost_usd)}</dd>
    <dt>Последняя сессия</dt><dd>${u.last_session ? `${fmtUsd(u.last_session.total_cost_usd)} · ${u.last_session.task_id || "—"} · ${fmtTime(u.last_session.recorded_at)}` : "—"}</dd>
  ` : "";
  return `<div class="usage-card"><div class="usage-title">${label}</div><dl class="kv">${rateLimitBlock}${sessionBlock}</dl></div>`;
}

async function refreshUsage() {
  const { usage } = await api("/api/usage");
  document.getElementById("usage-executors").innerHTML =
    renderExecutorUsage("Claude", usage.claude) + renderExecutorUsage("Codex", usage.codex);
}

async function openLatestLog(id) {
  try {
    const { task } = await api(`/api/tasks/${encodeURIComponent(id)}`);
    const sessions = (task.result && task.result.sessions) || [];
    if (!sessions.length) { document.getElementById("log-view").textContent = "У этой задачи ещё нет ни одной сессии."; return; }
    const logPath = sessions[sessions.length - 1].log;
    const basename = logPath.split(/[\\/]/).pop();
    const { content } = await api(`/api/logs?file=${encodeURIComponent(basename)}`);
    document.getElementById("log-view").dataset.raw = content;
    renderLog(content);
  } catch (e) {
    document.getElementById("log-view").textContent = `Не удалось загрузить лог: ${(e.body && e.body.error) || e.status}`;
  }
}

function renderLog(content) {
  const term = document.getElementById("log-search").value.trim();
  const view = document.getElementById("log-view");
  if (!term) { view.textContent = content; return; }
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  view.innerHTML = content.replace(new RegExp(escaped, "gi"), (m) => `<mark>${m}</mark>`);
}

// --- events panel ----------------------------------------------------------

async function refreshEvents() {
  const { events } = await api("/api/events?limit=100");
  if (events.length === lastEventCount) return;
  lastEventCount = events.length;
  const list = document.getElementById("events-list");
  list.innerHTML = events.slice().reverse().map((e) => `
    <div class="event-row">
      <span class="ts">${fmtTime(e.ts)}</span>
      <strong>${e.event}</strong> ${e.previous_state} → ${e.new_state}
      ${e.task_id ? ` · ${e.task_id}` : ""}
      ${e.reason ? ` · ${e.reason}` : ""}
    </div>
  `).join("");
}

// --- wiring ------------------------------------------------------------

function wireButtons() {
  document.getElementById("btn-start").onclick = () => runnerCommand("start");
  document.getElementById("btn-pause").onclick = () => runnerCommand("pause");
  document.getElementById("btn-resume").onclick = () => runnerCommand("resume");
  document.getElementById("btn-stop-stage").onclick = () => runnerCommand("stop-after-stage");
  document.getElementById("btn-emergency").onclick = async () => {
    const ok = await confirmAction(
      "Экстренная остановка немедленно прервёт текущий процесс Claude. Файлы не удаляются и Git не откатывается, но задача будет помечена как «interrupted» и потребует проверки перед следующим запуском. Продолжить?"
    );
    if (ok) runnerCommand("emergency-stop", { confirm: true });
  };
  // Queue card/row click and drag wiring happens per-refresh in
  // wireGroupInteractions() (called from refreshQueue()), since #queue-groups'
  // content is fully replaced on every poll -- a single static delegated
  // listener here would work too, but per-element wiring keeps drag state
  // (draggedKey/draggedId closures) scoped to one render pass, not leaked
  // across refreshes.
  document.getElementById("log-search").addEventListener("input", () => {
    const raw = document.getElementById("log-view").dataset.raw;
    if (raw) renderLog(raw);
  });
  document.getElementById("btn-copy-log").onclick = () => {
    const raw = document.getElementById("log-view").innerText;
    navigator.clipboard && navigator.clipboard.writeText(raw);
  };
}

async function runnerCommand(command, body) {
  try {
    await api(`/api/runner/${command}`, { method: "POST", body: JSON.stringify(body || {}) });
    await refreshStatus();
  } catch (e) {
    alert(`Команда «${command}» не выполнена: ${(e.body && e.body.error) || e.status}`);
  }
}

async function pollOnce() {
  try {
    await Promise.all([refreshStatus(), refreshQueue(), refreshEvents(), refreshUsage()]);
    setOffline(false);
  } catch {
    setOffline(true);
  }
}

wireButtons();
pollOnce();
setInterval(pollOnce, POLL_MS);
