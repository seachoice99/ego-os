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

// --- queue table -----------------------------------------------------------

const ACTIONS_BY_STATUS = {
  ready: ["hold"],
  held: ["unhold"],
  failed: ["retry"],
  waiting_for_auth: ["retry"],
  interrupted: ["retry"],
  blocked: [],
  waiting_for_limit: [],
};

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

function actionLabel(action) {
  return { hold: "Отложить", unhold: "Вернуть", retry: "Повторить" }[action] || action;
}

async function refreshQueue() {
  const { tasks } = await api("/api/tasks");
  const body = document.getElementById("queue-body");
  body.innerHTML = tasks.map((t) => `
    <tr>
      <td>${t.id}</td>
      <td>${t.title || ""}</td>
      <td>${t.priority}</td>
      <td><span class="status-pill status-${t.status}">${t.status}</span></td>
      <td>${t.release}</td>
      <td>${t.owner_approved ? "да" : "нет"}</td>
      <td>${t.blocked_reason || "—"}</td>
      <td class="row-actions">${rowActionsFor(t)}</td>
    </tr>
  `).join("");
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
  document.getElementById("queue-body").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-action]");
    if (!btn) return;
    handleRowAction(btn.dataset.action, btn.dataset.id);
  });
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
    await Promise.all([refreshStatus(), refreshQueue(), refreshEvents()]);
    setOffline(false);
  } catch {
    setOffline(true);
  }
}

wireButtons();
pollOnce();
setInterval(pollOnce, POLL_MS);
