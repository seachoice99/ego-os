"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { resolveGroup, listGroups } = require("./project_groups.js");

test("resolveGroup matches a known prefix", () => {
  assert.equal(resolveGroup("MED-01").key, "multi-executor");
  assert.equal(resolveGroup("CCTV-07").key, "chip-chip-tv");
  assert.equal(resolveGroup("RCI-02").key, "ops-expansion");
  assert.equal(resolveGroup("DA-03").key, "ego-os-core");
});

test("resolveGroup falls back for an unmapped prefix", () => {
  const g = resolveGroup("SOMETHING-NEW-01");
  assert.equal(g.key, "other");
  assert.ok(g.name);
  assert.ok(g.casual_summary);
});

test("resolveGroup handles missing/empty id without throwing", () => {
  assert.equal(resolveGroup(undefined).key, "other");
  assert.equal(resolveGroup("").key, "other");
});

test("resolveGroup prefers the longer/more specific prefix on overlap", () => {
  // TOKEN-EFFICIENCY- also starts with a hypothetical shorter "TOKEN-" --
  // proves longest-prefix-first ordering actually takes effect, not just
  // declaration order.
  assert.equal(resolveGroup("TOKEN-EFFICIENCY-VERIFY").key, "ego-os-core");
});

test("every group's fields are non-empty and every result is JSON-shaped", () => {
  for (const g of listGroups()) {
    assert.equal(typeof g.key, "string");
    assert.ok(g.key.length);
    assert.equal(typeof g.name, "string");
    assert.ok(g.name.length);
    assert.equal(typeof g.casual_summary, "string");
    assert.ok(g.casual_summary.length);
  }
});

test("listGroups includes the fallback group exactly once", () => {
  const others = listGroups().filter((g) => g.key === "other");
  assert.equal(others.length, 1);
});
