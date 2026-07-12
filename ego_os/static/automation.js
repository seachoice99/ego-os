"use strict";

/**
 * The /automation page's only client-side script. Everything else on this
 * page is a plain server-rendered form + redirect (Ego OS's existing
 * pattern, no fetch/polling anywhere else in the app) -- this file adds
 * exactly two small, self-contained behaviors that a plain <form> cannot
 * express: collapsing a casual project card, and drag-and-drop priority
 * reordering (which needs one POST, then a full page reload -- not a
 * live-updating SPA).
 */

document.querySelectorAll("[data-toggle-group]").forEach((btn) => {
  btn.addEventListener("click", () => {
    const key = btn.dataset.toggleGroup;
    const body = document.querySelector(`[data-group-body="${CSS.escape(key)}"]`);
    if (!body) return;
    const hidden = body.classList.toggle("hidden");
    btn.textContent = hidden ? "Технический список" : "Свернуть";
  });
});

const container = document.getElementById("queue-groups");

if (container) {
  function currentGroupOrder() {
    return [...container.querySelectorAll("[data-group-card]")].map((c) => c.dataset.groupCard);
  }

  function readyRowIdsInGroup(key) {
    const body = document.querySelector(`[data-group-body="${CSS.escape(key)}"]`);
    if (!body) return [];
    return [...body.querySelectorAll(".task-row[draggable='true']")].map((r) => r.dataset.rowId);
  }

  // Always resubmits the FULL flattened ready-task order from what's
  // currently on screen (every group, in its current order), never a
  // narrow per-group slice -- a partial submission would let two cards
  // independently reuse the same small queue_order numbers server-side
  // and silently scramble a previously-established global order.
  async function submitReorder() {
    const order = currentGroupOrder().flatMap(readyRowIdsInGroup);
    if (!order.length) return;
    try {
      const res = await fetch("/automation/tasks/reorder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ order }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        alert(`Не удалось сохранить новый порядок: ${body.detail || res.status}`);
      }
    } catch (e) {
      alert(`Не удалось сохранить новый порядок: ${e.message}`);
    } finally {
      location.reload();
    }
  }

  // --- drag-and-drop: group cards (global priority) -----------------------
  let draggedGroupKey = null;
  container.querySelectorAll("[data-group-card]").forEach((card) => {
    card.addEventListener("dragstart", (e) => {
      draggedGroupKey = card.dataset.groupCard;
      e.dataTransfer.effectAllowed = "move";
    });
    card.addEventListener("dragover", (e) => {
      if (!draggedGroupKey || draggedGroupKey === card.dataset.groupCard) return;
      e.preventDefault();
      card.classList.add("drag-over");
    });
    card.addEventListener("dragleave", () => card.classList.remove("drag-over"));
    card.addEventListener("drop", (e) => {
      e.preventDefault();
      card.classList.remove("drag-over");
      if (!draggedGroupKey || draggedGroupKey === card.dataset.groupCard) return;
      const draggedEl = container.querySelector(`[data-group-card="${CSS.escape(draggedGroupKey)}"]`);
      if (!draggedEl) return;
      container.insertBefore(draggedEl, card);
      draggedGroupKey = null;
      submitReorder();
    });
  });

  // --- drag-and-drop: rows inside one expanded group (local order) --------
  let draggedRowId = null, draggedRowGroup = null;
  container.querySelectorAll(".task-row[draggable='true']").forEach((row) => {
    row.addEventListener("dragstart", (e) => {
      draggedRowId = row.dataset.rowId;
      draggedRowGroup = row.dataset.group;
      e.dataTransfer.effectAllowed = "move";
      e.stopPropagation(); // never let this bubble into the group-card's own dragstart
    });
    row.addEventListener("dragover", (e) => {
      if (!draggedRowId || row.dataset.group !== draggedRowGroup || row.dataset.rowId === draggedRowId) return;
      e.preventDefault();
      e.stopPropagation();
      row.classList.add("drag-over");
    });
    row.addEventListener("dragleave", () => row.classList.remove("drag-over"));
    row.addEventListener("drop", (e) => {
      e.preventDefault();
      e.stopPropagation();
      row.classList.remove("drag-over");
      if (!draggedRowId || row.dataset.rowId === draggedRowId || row.dataset.group !== draggedRowGroup) return;
      const draggedRow = document.querySelector(`.task-row[data-row-id="${CSS.escape(draggedRowId)}"]`);
      if (!draggedRow) return;
      row.parentNode.insertBefore(draggedRow, row);
      draggedRowId = null;
      submitReorder();
    });
  });
}
