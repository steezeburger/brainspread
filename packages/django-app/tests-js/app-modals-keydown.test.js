// Tests for AppModals.onEscapeCapture — the global confirm/prompt/alert/
// picker dialog host's Escape/Enter routing.
//
// AppModals.js is a plain Vue options object hung off `window`, so it
// loads into a vm sandbox with a stub window and needs no bundler —
// same approach as the Page.js tests. `onEscapeCapture` only touches
// `this.queue`/`this.active` and sibling methods (never `document`),
// so it's invoked bound to a plain object replicating just that
// surface, no real Vue instance or DOM needed.
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
  "AppModals.js"
);

function loadAppModals() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), sandbox, {
    filename: SOURCE,
  });
  return sandbox.window.AppModals;
}

const AppModals = loadAppModals();

function makeContext(queue) {
  const ctx = { queue, ...AppModals.methods };
  Object.defineProperty(ctx, "active", {
    get() {
      return this.queue.length ? this.queue[this.queue.length - 1] : null;
    },
  });
  return ctx;
}

function fakeEscapeEvent() {
  const calls = { preventDefault: 0, stopPropagation: 0 };
  return {
    key: "Escape",
    preventDefault: () => calls.preventDefault++,
    stopPropagation: () => calls.stopPropagation++,
    calls,
  };
}

test("Escape on a confirm dialog cancels it", () => {
  let resolved;
  const ctx = makeContext([
    { id: 1, kind: "confirm", opts: {}, resolve: (v) => (resolved = v) },
  ]);
  const event = fakeEscapeEvent();

  ctx.onEscapeCapture.call(ctx, event);

  assert.equal(resolved, false);
  assert.equal(ctx.queue.length, 0);
  assert.equal(event.calls.preventDefault, 1);
  assert.equal(event.calls.stopPropagation, 1);
});

// The bug this covers: onEscapeCapture used to return immediately for
// pickPage/pickBlock on every key, including Escape, so cancelling a
// picker depended entirely on the search input still having focus —
// exactly the focus-fragile pattern that let Escape fall through to
// app.js's sidebar-closing handler once focus drifted off the input.
test("Escape on a page picker cancels it too", () => {
  let resolved;
  const ctx = makeContext([
    { id: 1, kind: "pickPage", opts: {}, resolve: (v) => (resolved = v) },
  ]);
  const event = fakeEscapeEvent();

  ctx.onEscapeCapture.call(ctx, event);

  assert.equal(resolved, null);
  assert.equal(ctx.queue.length, 0);
  assert.equal(event.calls.preventDefault, 1);
  assert.equal(event.calls.stopPropagation, 1);
});

test("Escape on a block picker cancels it too", () => {
  let resolved;
  const ctx = makeContext([
    { id: 1, kind: "pickBlock", opts: {}, resolve: (v) => (resolved = v) },
  ]);
  const event = fakeEscapeEvent();

  ctx.onEscapeCapture.call(ctx, event);

  assert.equal(resolved, null);
  assert.equal(ctx.queue.length, 0);
});

test("non-Escape keys on a picker are still left alone", () => {
  const ctx = makeContext([
    { id: 1, kind: "pickPage", opts: {}, resolve: () => {} },
  ]);
  const event = {
    key: "ArrowDown",
    preventDefault: () => {
      throw new Error("should not be called");
    },
    stopPropagation: () => {
      throw new Error("should not be called");
    },
  };

  assert.doesNotThrow(() => ctx.onEscapeCapture.call(ctx, event));
  assert.equal(ctx.queue.length, 1);
});

test("onEscapeCapture is a no-op with nothing in the queue", () => {
  const ctx = makeContext([]);
  const event = {
    key: "Escape",
    preventDefault: () => {
      throw new Error("should not be called");
    },
    stopPropagation: () => {
      throw new Error("should not be called");
    },
  };

  assert.doesNotThrow(() => ctx.onEscapeCapture.call(ctx, event));
});

test("Enter on an alert dialog confirms it", () => {
  let resolved = "unset";
  const ctx = makeContext([
    { id: 1, kind: "alert", opts: {}, resolve: (v) => (resolved = v) },
  ]);
  const event = {
    key: "Enter",
    preventDefault: () => {},
    stopPropagation: () => {},
  };

  ctx.onEscapeCapture.call(ctx, event);

  assert.equal(resolved, undefined);
  assert.equal(ctx.queue.length, 0);
});
