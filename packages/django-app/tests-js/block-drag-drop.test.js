// Tests for the block drag-and-drop reorder/re-nest logic in Page.js
// (issue #61). The drop handlers themselves need a live DOM/Vue
// context, but the two pure decision helpers they depend on —
// _dropForbidden (can this row accept the drop?) and
// _draggedTopBlocks (which dragged blocks are the roots of the
// dragged forest?) — are plain functions over the block tree and are
// exercised directly here.
//
// Run with `just test-js`.

const test = require("node:test");
const nodeAssert = require("node:assert/strict");
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
  const sandbox = { window: {}, console };
  sandbox.window.window = sandbox.window;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), sandbox, {
    filename: SOURCE,
  });
  return sandbox.window.Page;
}

const { methods } = loadPage();

// Arrays built inside the vm have a different Array.prototype, so
// deepEqual's prototype check fails on otherwise-equal values.
// Compare by value instead.
const assert = {
  equal: nodeAssert.equal,
  deepEqual: (actual, expected, message) =>
    nodeAssert.deepEqual(JSON.parse(JSON.stringify(actual)), expected, message),
};

// A (root)
//   A1 (child of A)
//     A1a (child of A1)
// B (root)
function buildTree() {
  const a1a = { uuid: "a1a", children: [] };
  const a1 = { uuid: "a1", children: [a1a] };
  const a = { uuid: "a", parent: null, children: [a1] };
  a1.parent = a;
  a1a.parent = a1;
  const b = { uuid: "b", parent: null, children: [] };
  return { a, a1, a1a, b, directBlocks: [a, b] };
}

function contextWith(blockDrag, directBlocks) {
  return {
    blockDrag,
    directBlocks,
    flattenBlockTree: methods.flattenBlockTree,
  };
}

test("_dropForbidden allows a drop outside the dragged subtree", () => {
  const { a, b } = buildTree();
  const ctx = contextWith({ uuids: new Set([a.uuid]) });

  assert.equal(methods._dropForbidden.call(ctx, b), false);
});

test("_dropForbidden refuses dropping a block onto itself", () => {
  const { a } = buildTree();
  const ctx = contextWith({ uuids: new Set([a.uuid]) });

  assert.equal(methods._dropForbidden.call(ctx, a), true);
});

test("_dropForbidden refuses dropping onto a direct or deep descendant", () => {
  const { a, a1, a1a } = buildTree();
  const ctx = contextWith({ uuids: new Set([a.uuid]) });

  assert.equal(methods._dropForbidden.call(ctx, a1), true);
  assert.equal(methods._dropForbidden.call(ctx, a1a), true);
});

test("_dropForbidden refuses everything when there is no live drag", () => {
  const { b } = buildTree();
  const ctx = contextWith(null);

  assert.equal(methods._dropForbidden.call(ctx, b), true);
});

test("_draggedTopBlocks returns just the dragged root when its subtree is fully selected", () => {
  const { a, a1, directBlocks } = buildTree();
  const ctx = contextWith({ uuids: new Set([a.uuid, a1.uuid]) }, directBlocks);

  const tops = methods._draggedTopBlocks.call(ctx);

  assert.deepEqual(
    tops.map((block) => block.uuid),
    ["a"]
  );
});

test("_draggedTopBlocks keeps unrelated dragged blocks as separate roots", () => {
  const { a1, b, directBlocks } = buildTree();
  const ctx = contextWith({ uuids: new Set([a1.uuid, b.uuid]) }, directBlocks);

  const tops = methods._draggedTopBlocks.call(ctx);

  assert.deepEqual(
    tops.map((block) => block.uuid),
    ["a1", "b"]
  );
});

test("_draggedTopBlocks returns nothing when no drag is in progress", () => {
  const { directBlocks } = buildTree();
  const ctx = contextWith(null, directBlocks);

  assert.deepEqual(methods._draggedTopBlocks.call(ctx), []);
});
