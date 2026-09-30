// Tests for Page.formatContentWithTags, the block-content markdown
// renderer used in view mode.
//
// Page.js is a plain Vue options object hung off `window`, so it loads
// into a vm sandbox with a stub window and needs no bundler — same
// approach as emoji.test.js. `formatContentWithTags` calls sibling
// methods (`safeUrl`, `escapeAttr`, `escapeHtml`) via `this`, so it's
// invoked bound to an object built from `Page.methods` itself.
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

function loadFormatContentWithTags() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), sandbox, {
    filename: SOURCE,
  });
  const ctx = { emojiRenderKey: 0, ...sandbox.window.Page.methods };
  return (content, blockType, properties) =>
    ctx.formatContentWithTags.call(ctx, content, blockType, properties);
}

const format = loadFormatContentWithTags();

test("issue #240: a cron trigger property keeps its literal stars", () => {
  const html = format("trigger:: schedule cron 0 6 1 * *");
  assert.match(html, /data-property-key="trigger"/);
  assert.match(html, /data-property-value="schedule cron 0 6 1 \* \*"/);
  assert.match(html, /schedule cron 0 6 1 \* \*/);
  // The old bug: `1 * *` was read as an emphasis span wrapping a
  // single space, swallowing both stars.
  assert.doesNotMatch(html, /markdown-italic/);
});

test("a line-start property with a multi-word value becomes one chip", () => {
  const html = format("trigger:: schedule daily 6:00");
  assert.match(html, /data-property-key="trigger"/);
  assert.match(html, /data-property-value="schedule daily 6:00"/);
});

test("a second inline property on the same line still splits out", () => {
  const html = format("Ping sweep\ntrigger:: manual\nfor:: 5,10,15");
  assert.match(html, /data-property-key="trigger"[^>]*>trigger::manual/);
  assert.match(html, /data-property-key="for"[^>]*>for::5,10,15/);
});

test("a line-start value stops at the next inline key:: token", () => {
  const html = format("priority:: high status:: open");
  assert.match(html, /data-property-key="priority"/);
  assert.match(html, /data-property-value="high"/);
  assert.match(html, /data-property-key="status"/);
  assert.match(html, /data-property-value="open"/);
});

test("a property elsewhere on the line stays single-token", () => {
  const html = format("buy milk priority:: high");
  assert.match(html, /data-property-key="priority"/);
  assert.match(html, /data-property-value="high"/);
  assert.match(html, /buy milk/);
});

test("plain emphasis still renders", () => {
  assert.match(format("this is *italic* text"), /markdown-italic">italic</);
  assert.match(format("this is **bold** text"), /markdown-bold">bold</);
});

// `key::value` with no space after `::` is accepted alongside the
// `key:: value` form throughout — both patterns' `::\s*` treats the
// space as optional, so this is existing behavior, not new parsing.
// These tests just make that explicit instead of leaving it implicit
// in the regex.
test("a line-start single-word property needs no space after ::", () => {
  const html = format("priority::high");
  assert.match(html, /data-property-key="priority"/);
  assert.match(html, /data-property-value="high"/);
  assert.match(html, />priority::high</);
});

test("a line-start multi-word property needs no space after ::", () => {
  const html = format("trigger::schedule cron 0 6 1 * *");
  assert.match(html, /data-property-key="trigger"/);
  assert.match(html, /data-property-value="schedule cron 0 6 1 \* \*"/);
  assert.doesNotMatch(html, /markdown-italic/);
});

test("a mid-line property needs no space after ::", () => {
  const html = format("buy milk priority::high");
  assert.match(html, /data-property-key="priority"/);
  assert.match(html, /data-property-value="high"/);
  assert.match(html, /buy milk/);
});
