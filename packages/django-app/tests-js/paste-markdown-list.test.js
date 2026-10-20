// Tests for Page.parseMarkdownList / Page.buildBlockTree, the pasted-text
// importer behind onBlockPaste in Page.js.
//
// Page.js is a plain Vue options object hung off `window`, so it loads
// into a vm sandbox with a stub window and needs no bundler — same
// approach as format-content-with-tags.test.js.
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

function loadPageMethods() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), sandbox, {
    filename: SOURCE,
  });
  return sandbox.window.Page.methods;
}

const methods = loadPageMethods();
const parseMarkdownList = (text) =>
  methods.parseMarkdownList.call(methods, text);
const buildBlockTree = (items) => methods.buildBlockTree.call(methods, items);

test("a flat bulleted list becomes one item per line", () => {
  const items = parseMarkdownList("- one\n- two\n- three");
  assert.deepEqual(
    Array.from(items, (i) => i.content),
    ["one", "two", "three"]
  );
});

test("plain text with no leading bullet is left for native paste", () => {
  assert.deepEqual(
    Array.from(parseMarkdownList("just some text\nmore text")),
    []
  );
});

// The bug this covers: serializeBlockToMarkdown exports a multi-line
// block's embedded newlines as plain, unbulleted lines sitting directly
// under that block's `- ` line (see Page.js's serializeBlockToMarkdown).
// Before this fix, parseMarkdownList silently dropped those lines on
// paste — copying a multi-line block and pasting it elsewhere lost
// every line after the first.
test("a non-bulleted line after a list item is a continuation, not dropped", () => {
  const items = parseMarkdownList(
    '- trigger:: schedule daily 0:00\naction:: apply_template "daily log block" to today\nenabled:: true'
  );
  assert.equal(items.length, 1);
  assert.equal(
    items[0].content,
    'trigger:: schedule daily 0:00\naction:: apply_template "daily log block" to today\nenabled:: true'
  );
});

test("continuation lines attach to the most recent item, not earlier ones", () => {
  const items = parseMarkdownList(
    "- first\ncontinues first\n- second\ncontinues second"
  );
  assert.deepEqual(
    Array.from(items, (i) => i.content),
    ["first\ncontinues first", "second\ncontinues second"]
  );
});

test("a multi-line child block round-trips into the tree with the right parent", () => {
  const items = parseMarkdownList(
    [
      "- Daily automations",
      "  - #automation Add empty log block",
      "trigger:: schedule daily 0:00",
      "enabled:: true",
      "  - #automation Sweep sticky blocks",
      "trigger:: schedule daily 0:01",
      "enabled:: true",
      "- Weekly automations",
    ].join("\n")
  );
  const tree = buildBlockTree(items);

  assert.equal(tree.length, 2);
  assert.equal(tree[0].content, "Daily automations");
  assert.equal(tree[0].children.length, 2);
  assert.equal(
    tree[0].children[0].content,
    "#automation Add empty log block\ntrigger:: schedule daily 0:00\nenabled:: true"
  );
  assert.equal(
    tree[0].children[1].content,
    "#automation Sweep sticky blocks\ntrigger:: schedule daily 0:01\nenabled:: true"
  );
  assert.equal(tree[1].content, "Weekly automations");
  assert.equal(tree[1].children.length, 0);
});

// A continuation line has no bullet of its own, so it must never be
// pushed as an `items` entry — buildBlockTree would otherwise see an
// extra node with no indent-derived level.
test("continuation lines don't count as their own tree nodes", () => {
  const items = parseMarkdownList("- one\ncontinuation\n- two");
  assert.equal(items.length, 2);
  const tree = buildBlockTree(items);
  assert.equal(tree.length, 2);
});
