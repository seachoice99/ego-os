"use strict";

/**
 * Pure lookup: which casual "project" a task belongs to, derived from its
 * id prefix -- never a new required field on the ~30 existing task YAMLs.
 * Used by the dashboard (via runner_control.summarizeTask()) to collapse a
 * large initiative's many tasks into one card instead of 8-9 distracting
 * rows. Adding a new initiative means adding one row here, not touching
 * every task file it owns.
 */

const GROUPS = [
  {
    key: "ego-os-core",
    name: "Развитие Ego OS",
    casual_summary: "Сама платформа: раннер, деплой, скиллы, отчёты.",
    prefixes: ["SR-", "RUNNER-", "DA-", "AGENT-", "TOKEN-EFFICIENCY-", "SERVER-RUNNER-"],
  },
  {
    key: "ops-expansion",
    name: "Операционное расширение",
    casual_summary: "Исследования, видимость раннера, политика расхода токенов.",
    prefixes: ["ERE-", "RCI-", "UOP-"],
  },
  {
    key: "chip-chip-tv",
    name: "Цып-Цып ТВ",
    casual_summary: "Отдельный продукт: лицензирование Chip-Chip TV.",
    prefixes: ["CCTV-"],
  },
  {
    key: "multi-executor",
    name: "Клод + Кодекс работают вместе",
    casual_summary: "Один раннер, который сам решает: Claude, Codex или бесплатная модель.",
    prefixes: ["MED-"],
  },
];

const FALLBACK_GROUP = { key: "other", name: "Другое", casual_summary: "Пока без своей группы." };

// Longest-prefix-first so a future, more specific prefix (e.g. "RUNNER-UI-")
// never gets shadowed by a shorter, earlier-declared one (e.g. "RUNNER-").
const SORTED_PREFIXES = GROUPS
  .flatMap((g) => g.prefixes.map((prefix) => ({ prefix, group: g })))
  .sort((a, b) => b.prefix.length - a.prefix.length);

function resolveGroup(taskId) {
  const id = String(taskId || "");
  const match = SORTED_PREFIXES.find(({ prefix }) => id.startsWith(prefix));
  const group = match ? match.group : FALLBACK_GROUP;
  return { key: group.key, name: group.name, casual_summary: group.casual_summary };
}

function listGroups() {
  return GROUPS.map((g) => ({ key: g.key, name: g.name, casual_summary: g.casual_summary })).concat([FALLBACK_GROUP]);
}

module.exports = { resolveGroup, listGroups, GROUPS, FALLBACK_GROUP };
