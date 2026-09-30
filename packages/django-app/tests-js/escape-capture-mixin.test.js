// Tests for brainspreadEscapeCaptureMixin (services/escape-capture.js) —
// the shared Vue mixin that toggles a document-level, capture-phase
// keydown listener based on a component's own open/active flag.
//
// This mixin is the DRY extraction of a pattern that used to be
// hand-rolled in AppModals, HelpModal, HistoryModal, BlockInfoModal,
// SettingsModal, ScheduleBlockPopover, BlockChatPopover, and Page.js's
// share modal — each with its own watcher + beforeUnmount wiring. See
// app-modals-keydown.test.js and page-share-modal-keydown.test.js for
// coverage of each component's own Escape-handling *logic*; this file
// only covers the mixin's generic wiring.
//
// The mixin calls `document.addEventListener`/`removeEventListener`
// directly (not `window.document`), so unlike the method-only tests
// elsewhere in this directory, this sandbox needs a fake `document`
// global to exercise that code path.
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
  "services",
  "escape-capture.js"
);

function fakeDocument() {
  const listeners = [];
  return {
    listeners,
    addEventListener(type, handler, capture) {
      listeners.push({ type, handler, capture });
    },
    removeEventListener(type, handler, capture) {
      const i = listeners.findIndex(
        (l) => l.type === type && l.handler === handler && l.capture === capture
      );
      if (i !== -1) listeners.splice(i, 1);
    },
  };
}

function loadMixin(doc) {
  const sandbox = { window: {}, document: doc };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), sandbox, {
    filename: SOURCE,
  });
  return sandbox.window.brainspreadEscapeCaptureMixin;
}

// Builds a fake component instance. `$watch` is a stub that just
// records the callback rather than reacting to real changes — the
// test drives the flag and invokes the callback itself, the same way
// the AppModals tests drive `onKeydown` directly rather than going
// through a real Vue render cycle.
function makeComponent(mixin, { flag, handlerName, initial = false }) {
  const calls = [];
  const ctx = {
    [flag]: initial,
    _watchers: {},
    $watch(name, cb) {
      ctx._watchers[name] = cb;
      return () => {
        delete ctx._watchers[name];
      };
    },
    escapeCaptureFlag: () => flag,
    escapeCaptureHandlerName: () => handlerName,
    [handlerName](event) {
      calls.push(event);
    },
    ...mixin.methods,
  };
  ctx.created = mixin.created;
  ctx.mounted = mixin.mounted;
  ctx.beforeUnmount = mixin.beforeUnmount;
  ctx.calls = calls;
  return ctx;
}

test("mounting while closed does not bind a listener", () => {
  const doc = fakeDocument();
  const mixin = loadMixin(doc);
  const ctx = makeComponent(mixin, { flag: "isOpen", handlerName: "onKey" });

  ctx.created.call(ctx);
  ctx.mounted.call(ctx);

  assert.equal(doc.listeners.length, 0);
});

test("mounting while already open binds a capture-phase listener", () => {
  const doc = fakeDocument();
  const mixin = loadMixin(doc);
  const ctx = makeComponent(mixin, {
    flag: "isOpen",
    handlerName: "onKey",
    initial: true,
  });

  ctx.created.call(ctx);
  ctx.mounted.call(ctx);

  assert.equal(doc.listeners.length, 1);
  assert.equal(doc.listeners[0].type, "keydown");
  assert.equal(doc.listeners[0].capture, true);
});

test("flipping the flag open binds, closed unbinds", () => {
  const doc = fakeDocument();
  const mixin = loadMixin(doc);
  const ctx = makeComponent(mixin, { flag: "isOpen", handlerName: "onKey" });
  ctx.created.call(ctx);
  ctx.mounted.call(ctx);

  ctx._watchers.isOpen(true);
  assert.equal(doc.listeners.length, 1);

  ctx._watchers.isOpen(false);
  assert.equal(doc.listeners.length, 0);
});

test("the bound listener forwards to the named handler", () => {
  const doc = fakeDocument();
  const mixin = loadMixin(doc);
  const ctx = makeComponent(mixin, {
    flag: "isOpen",
    handlerName: "onKey",
    initial: true,
  });
  ctx.created.call(ctx);
  ctx.mounted.call(ctx);

  const event = { key: "Escape" };
  doc.listeners[0].handler(event);

  assert.equal(ctx.calls.length, 1);
  assert.equal(ctx.calls[0], event);
});

test("beforeUnmount removes the listener even while still open", () => {
  const doc = fakeDocument();
  const mixin = loadMixin(doc);
  const ctx = makeComponent(mixin, {
    flag: "isOpen",
    handlerName: "onKey",
    initial: true,
  });
  ctx.created.call(ctx);
  ctx.mounted.call(ctx);
  assert.equal(doc.listeners.length, 1);

  ctx.beforeUnmount.call(ctx);

  assert.equal(doc.listeners.length, 0);
});

test("different components can use different flag/handler names", () => {
  const doc = fakeDocument();
  const mixin = loadMixin(doc);
  const ctx = makeComponent(mixin, {
    flag: "shareModalOpen",
    handlerName: "handleShareModalKeydown",
  });
  ctx.created.call(ctx);
  ctx.mounted.call(ctx);

  ctx._watchers.shareModalOpen(true);
  const event = { key: "Escape" };
  doc.listeners[0].handler(event);

  assert.equal(ctx.calls.length, 1);
});
