// Tests for Page.onEscapeCapture — the share modal's Escape
// handler.
//
// Page.js is a plain Vue options object hung off `window`, so it loads
// into a vm sandbox with a stub window and needs no bundler — same
// approach as format-content-with-tags.test.js. `onEscapeCapture`
// only calls `this.closeShareModal`, so it's invoked bound to a plain
// object stubbing just that method.
//
// This closes the bug where Escape, after a click on the modal
// backdrop moved focus off any input, fell through to app.js's
// document-level handler and closed the sidebar instead of the modal
// — onEscapeCapture is bound in the capture phase (see
// openShareModal), so it runs and calls stopPropagation() before that
// bubble-phase handler ever sees the event.
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
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), sandbox, {
    filename: SOURCE,
  });
  return sandbox.window.Page;
}

const Page = loadPage();

function makeContext() {
  let closed = false;
  return {
    onEscapeCapture: Page.methods.onEscapeCapture,
    closeShareModal: () => {
      closed = true;
    },
    get closed() {
      return closed;
    },
  };
}

function fakeEvent(key) {
  const calls = { preventDefault: 0, stopPropagation: 0 };
  return {
    key,
    preventDefault: () => calls.preventDefault++,
    stopPropagation: () => calls.stopPropagation++,
    calls,
  };
}

test("Escape closes the share modal and stops the event", () => {
  const ctx = makeContext();
  const event = fakeEvent("Escape");

  ctx.onEscapeCapture(event);

  assert.equal(ctx.closed, true);
  assert.equal(event.calls.preventDefault, 1);
  assert.equal(event.calls.stopPropagation, 1);
});

test("other keys are left alone", () => {
  const ctx = makeContext();
  const event = fakeEvent("a");

  ctx.onEscapeCapture(event);

  assert.equal(ctx.closed, false);
  assert.equal(event.calls.preventDefault, 0);
  assert.equal(event.calls.stopPropagation, 0);
});
