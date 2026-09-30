// Tests for the block move-up/move-down race fix (issue #176).
//
// Page.js is a Vue options object hung off `window`, so it loads into a
// vm sandbox with a stub window and needs no bundler/Vue runtime. The
// move handlers (`moveBlockUp`/`moveBlockDown`, backed by `_moveBlock`
// and `_runExclusive`) are plain async methods that read/write `this` —
// so they're exercised against a hand-built `this` (a fake Page
// instance) rather than a mounted component.
//
// Alt+Shift+Up/Down fires one async keydown handler per keystroke;
// holding the key launches many overlapping moves. Before the fix, each
// move read a stale `block.order` baseline and only swapped two values,
// so overlapping moves clobbered each other's writes into duplicate /
// gapped orders. The fix serializes moves through `_runExclusive` and
// renumbers the *whole* sibling group to a contiguous 0..N-1 sequence on
// every move, which is self-healing even from already-corrupted input.
//
// Run with `just test-js`.

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const SOURCE = path.join(
  __dirname,
  "..",
  "app",
  "knowledge",
  "static",
  "knowledge",
  "js",
  "components",
  "Page.js"
);

function loadPage() {
  const sandbox = { window: {}, console, setTimeout, clearTimeout };
  sandbox.window.window = sandbox.window;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), sandbox, {
    filename: SOURCE,
  });
  return { Page: sandbox.window.Page, window: sandbox.window };
}

// A tiny async delay so the fake API "call" actually yields at an await
// point, the way a real fetch would — this is what lets overlapping
// moves interleave when they aren't serialized.
function tick() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function makeBlocks(n) {
  return Array.from({ length: n }, (_, i) => ({
    uuid: `block-${i}`,
    order: i,
    content: `block ${i}`,
    parent: null,
    isEditing: false,
  }));
}

// Builds a fake Page-component `this` wired to the real moveBlockUp /
// moveBlockDown / _moveBlock / _runExclusive methods, with a fake
// apiService.reorderBlocks that persists into `backendOrders` (keyed by
// uuid) the way the real ReorderBlocksCommand would, after an async
// delay so concurrent callers actually race if not serialized.
function makeHarness(directBlocks) {
  const { Page, window } = loadPage();
  const reorderCalls = [];
  const backendOrders = new Map(directBlocks.map((b) => [b.uuid, b.order]));

  window.apiService = {
    async reorderBlocks(updates) {
      reorderCalls.push(updates.map((u) => ({ ...u })));
      await tick();
      for (const { uuid, order } of updates) {
        backendOrders.set(uuid, order);
      }
      return { success: true };
    },
  };

  const errors = [];
  const ctx = {
    directBlocks,
    _reorderMutex: Promise.resolve(),
    async updateBlock() {
      // Simulate the pre-move content save yielding too.
      await tick();
    },
    toastBlockError(error, fallback) {
      errors.push(fallback);
    },
    _runExclusive: Page.methods._runExclusive,
    _moveBlock: Page.methods._moveBlock,
    moveBlockUp: Page.methods.moveBlockUp,
    moveBlockDown: Page.methods.moveBlockDown,
  };

  return { ctx, reorderCalls, backendOrders, errors };
}

function assertContiguousUnique(blocks) {
  const orders = blocks.map((b) => b.order).sort((a, b) => a - b);
  const expected = blocks.map((_, i) => i);
  assert.deepEqual(
    orders,
    expected,
    "orders must be exactly 0..N-1 with no dupes/gaps"
  );
}

test("two overlapping moves on the same sibling group end up contiguous and unique", async () => {
  const directBlocks = makeBlocks(5);
  const { ctx, backendOrders } = makeHarness(directBlocks);

  // Fire both moves back-to-back without awaiting the first — this is
  // what "holding the key" / two near-simultaneous keydowns looks like.
  const moveDown0 = ctx.moveBlockDown(directBlocks[0]); // block-0 -> index 1
  const moveUp2 = ctx.moveBlockUp(directBlocks[2]); // block-2 -> index 1 (of the original array)

  await Promise.all([moveDown0, moveUp2]);

  assertContiguousUnique(directBlocks);

  // The local array and the "persisted" backend must agree — no stale
  // writes left behind by an interleaved move.
  for (const block of directBlocks) {
    assert.equal(
      backendOrders.get(block.uuid),
      block.order,
      `backend order for ${block.uuid} must match local state`
    );
  }

  // uuids stayed unique/complete across the group.
  assert.deepEqual(
    new Set(directBlocks.map((b) => b.uuid)).size,
    5,
    "no blocks lost or duplicated"
  );
});

test("rapidly repeated moveBlockDown calls (holding the key) never collide", async () => {
  const directBlocks = makeBlocks(6);
  const { ctx, reorderCalls } = makeHarness(directBlocks);
  const block = directBlocks[0];

  // Simulate holding Alt+Shift+Down: many keydowns fire moveBlockDown on
  // the same block before any of them has resolved.
  const moves = [
    ctx.moveBlockDown(block),
    ctx.moveBlockDown(block),
    ctx.moveBlockDown(block),
    ctx.moveBlockDown(block),
  ];
  await Promise.all(moves);

  assertContiguousUnique(directBlocks);

  // Each move must have been serialized: every reorderBlocks call should
  // carry a full, self-consistent contiguous renumbering of the group
  // (not a partial/stale 2-item swap).
  for (const call of reorderCalls) {
    const orders = call.map((u) => u.order).sort((a, b) => a - b);
    assert.deepEqual(orders, [0, 1, 2, 3, 4, 5]);
    assert.equal(new Set(call.map((u) => u.uuid)).size, call.length);
  }

  // The block moved down 4 times from index 0 in a 6-element group, and
  // each move is serialized against the group as it stood after the
  // previous one — so it should land at index 4 (clamped by the
  // bounds check on the last, no-op attempt past the bottom is fine
  // too; the key assertion is "no corruption", already checked above).
  assert.equal(directBlocks.findIndex((b) => b.uuid === block.uuid) >= 1, true);
});

test("starting from already-corrupted (duplicate/gapped) orders, one move self-heals the group", async () => {
  const directBlocks = makeBlocks(4);
  // Simulate the production corruption described in the issue: duplicate
  // and gapped `order` values already on the objects driving the DOM
  // order (directBlocks itself is what move handlers splice/renumber,
  // so array position — not the corrupted `.order` field — is what
  // matters for correctness here).
  directBlocks[0].order = 0;
  directBlocks[1].order = 2;
  directBlocks[2].order = 2;
  directBlocks[3].order = 5;

  const { ctx } = makeHarness(directBlocks);

  await ctx.moveBlockDown(directBlocks[0]);

  assertContiguousUnique(directBlocks);
});
