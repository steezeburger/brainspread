// Tests for the shared swipe-to-close gesture util (issue #115).
//
// swipe.js is a plain IIFE that hangs itself off `window`, so it loads
// into a vm sandbox with a stub window and needs no bundler/DOM. The
// touch-event wiring (createSwipeCloseTracker) is exercised against
// hand-built fake touch events and fake DOM elements (plain objects with
// scrollWidth/clientWidth/scrollLeft/offsetWidth/parentElement) rather
// than a real DOM, matching the rest of this test suite.
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
  "swipe.js"
);

function loadSwipe(win) {
  const sandbox = { window: win || {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), sandbox, {
    filename: SOURCE,
  });
  return sandbox.window.brainspreadSwipe;
}

function fakeEl(overrides) {
  return Object.assign(
    {
      scrollWidth: 100,
      clientWidth: 100,
      scrollLeft: 0,
      offsetWidth: 100,
      parentElement: null,
    },
    overrides
  );
}

function touchEvent(target, x, y) {
  return {
    target,
    touches: [{ clientX: x, clientY: y }],
    changedTouches: [{ clientX: x, clientY: y }],
  };
}

// --- isTouchViewport ---

test("isTouchViewport: false above the 768px breakpoint", () => {
  const swipe = loadSwipe();
  assert.equal(
    swipe.isTouchViewport({
      innerWidth: 1024,
      matchMedia: () => ({ matches: true }),
    }),
    false
  );
});

test("isTouchViewport: true at/below 768px with a coarse pointer", () => {
  const swipe = loadSwipe();
  assert.equal(
    swipe.isTouchViewport({
      innerWidth: 768,
      matchMedia: () => ({ matches: true }),
    }),
    true
  );
});

test("isTouchViewport: false at a small width but a fine pointer (touchscreen laptop)", () => {
  const swipe = loadSwipe();
  assert.equal(
    swipe.isTouchViewport({
      innerWidth: 500,
      matchMedia: () => ({ matches: false }),
    }),
    false
  );
});

test("isTouchViewport: falls back to true when matchMedia is unavailable", () => {
  const swipe = loadSwipe();
  assert.equal(swipe.isTouchViewport({ innerWidth: 400 }), true);
});

// --- findHorizontalScrollAncestor ---

test("findHorizontalScrollAncestor: finds a scrollable ancestor between target and root", () => {
  const swipe = loadSwipe();
  const root = fakeEl({ scrollWidth: 400, clientWidth: 400 });
  const scroller = fakeEl({
    scrollWidth: 800,
    clientWidth: 400,
    parentElement: root,
  });
  const leaf = fakeEl({
    scrollWidth: 50,
    clientWidth: 50,
    parentElement: scroller,
  });
  assert.equal(swipe.findHorizontalScrollAncestor(leaf, root), scroller);
});

test("findHorizontalScrollAncestor: returns null when nothing overflows before root", () => {
  const swipe = loadSwipe();
  const root = fakeEl();
  const leaf = fakeEl({ parentElement: root });
  assert.equal(swipe.findHorizontalScrollAncestor(leaf, root), null);
});

test("findHorizontalScrollAncestor: stops at root and never reports root itself", () => {
  const swipe = loadSwipe();
  const root = fakeEl({ scrollWidth: 800, clientWidth: 400 });
  assert.equal(swipe.findHorizontalScrollAncestor(root, root), null);
});

// --- hasScrollRoomTowardDx ---

test("hasScrollRoomTowardDx: rightward drag has room while scrollLeft > 0", () => {
  const swipe = loadSwipe();
  assert.equal(
    swipe.hasScrollRoomTowardDx(fakeEl({ scrollLeft: 20 }), 10),
    true
  );
  assert.equal(
    swipe.hasScrollRoomTowardDx(fakeEl({ scrollLeft: 0 }), 10),
    false
  );
});

test("hasScrollRoomTowardDx: leftward drag has room until the end is reached", () => {
  const swipe = loadSwipe();
  const el = fakeEl({ scrollWidth: 500, clientWidth: 100, scrollLeft: 100 });
  assert.equal(swipe.hasScrollRoomTowardDx(el, -10), true);
  const atEnd = fakeEl({ scrollWidth: 500, clientWidth: 100, scrollLeft: 400 });
  assert.equal(swipe.hasScrollRoomTowardDx(atEnd, -10), false);
});

test("hasScrollRoomTowardDx: false for a null element or dx of 0", () => {
  const swipe = loadSwipe();
  assert.equal(swipe.hasScrollRoomTowardDx(null, 10), false);
  assert.equal(
    swipe.hasScrollRoomTowardDx(fakeEl({ scrollLeft: 20 }), 0),
    false
  );
});

// --- isClosingSwipe ---

test("isClosingSwipe: leftward past threshold closes a -1 (left nav) gesture", () => {
  const swipe = loadSwipe();
  assert.equal(swipe.isClosingSwipe(-80, 5, -1, 60), true);
  assert.equal(swipe.isClosingSwipe(-40, 5, -1, 60), false);
});

test("isClosingSwipe: rightward past threshold closes a +1 (chat panel) gesture", () => {
  const swipe = loadSwipe();
  assert.equal(swipe.isClosingSwipe(80, 5, 1, 60), true);
  assert.equal(swipe.isClosingSwipe(40, 5, 1, 60), false);
});

test("isClosingSwipe: wrong-direction drag never closes", () => {
  const swipe = loadSwipe();
  assert.equal(swipe.isClosingSwipe(80, 5, -1, 60), false);
  assert.equal(swipe.isClosingSwipe(-80, 5, 1, 60), false);
});

test("isClosingSwipe: a vertical-dominant drag passes through even past the threshold", () => {
  const swipe = loadSwipe();
  assert.equal(swipe.isClosingSwipe(-80, 60, -1, 60), false);
});

// --- closeThreshold ---

test("closeThreshold: floors at the minimum px regardless of width", () => {
  const swipe = loadSwipe();
  assert.equal(swipe.closeThreshold(100, 60, 0.25), 60);
});

test("closeThreshold: 25% of width wins once the surface is wide enough", () => {
  const swipe = loadSwipe();
  assert.equal(swipe.closeThreshold(400, 60, 0.25), 100);
});

// --- createSwipeCloseTracker ---

function mobileWindow() {
  return { innerWidth: 400, matchMedia: () => ({ matches: true }) };
}

test("tracker: a leftward drag past threshold closes the left nav", () => {
  const swipe = loadSwipe(mobileWindow());
  const root = fakeEl({ offsetWidth: 400 });
  let closed = false;
  const tracker = swipe.createSwipeCloseTracker({
    direction: -1,
    root: () => root,
    onClose: () => {
      closed = true;
    },
  });
  const target = fakeEl({ parentElement: root });
  tracker.handleTouchStart(touchEvent(target, 300, 200));
  tracker.handleTouchMove(touchEvent(target, 200, 205));
  tracker.handleTouchEnd(touchEvent(target, 150, 205));
  assert.equal(closed, true);
});

test("tracker: a short drag under threshold does not close", () => {
  const swipe = loadSwipe(mobileWindow());
  const root = fakeEl({ offsetWidth: 400 });
  let closed = false;
  const tracker = swipe.createSwipeCloseTracker({
    direction: -1,
    root: () => root,
    onClose: () => {
      closed = true;
    },
  });
  const target = fakeEl({ parentElement: root });
  tracker.handleTouchStart(touchEvent(target, 300, 200));
  tracker.handleTouchEnd(touchEvent(target, 280, 200));
  assert.equal(closed, false);
});

test("tracker: a vertical scroll inside the sidebar never closes it", () => {
  const swipe = loadSwipe(mobileWindow());
  const root = fakeEl({ offsetWidth: 400 });
  let closed = false;
  const tracker = swipe.createSwipeCloseTracker({
    direction: -1,
    root: () => root,
    onClose: () => {
      closed = true;
    },
  });
  const target = fakeEl({ parentElement: root });
  tracker.handleTouchStart(touchEvent(target, 300, 100));
  tracker.handleTouchEnd(touchEvent(target, 220, 400));
  assert.equal(closed, false);
});

test("tracker: gated off on desktop viewports", () => {
  const swipe = loadSwipe({
    innerWidth: 1200,
    matchMedia: () => ({ matches: false }),
  });
  const root = fakeEl({ offsetWidth: 1200 });
  let closed = false;
  const tracker = swipe.createSwipeCloseTracker({
    direction: -1,
    root: () => root,
    onClose: () => {
      closed = true;
    },
  });
  const target = fakeEl({ parentElement: root });
  tracker.handleTouchStart(touchEvent(target, 900, 200));
  tracker.handleTouchEnd(touchEvent(target, 700, 200));
  assert.equal(closed, false);
});

test("tracker: a right-swipe over a code block with scroll room left scrolls instead of closing the chat panel", () => {
  const swipe = loadSwipe(mobileWindow());
  const panel = fakeEl({ offsetWidth: 400 });
  const codeBlock = fakeEl({
    scrollWidth: 800,
    clientWidth: 400,
    scrollLeft: 200,
    parentElement: panel,
  });
  let closed = false;
  const tracker = swipe.createSwipeCloseTracker({
    direction: 1,
    root: () => panel,
    onClose: () => {
      closed = true;
    },
  });
  tracker.handleTouchStart(touchEvent(codeBlock, 100, 200));
  tracker.handleTouchMove(touchEvent(codeBlock, 200, 202));
  tracker.handleTouchEnd(touchEvent(codeBlock, 300, 202));
  assert.equal(closed, false);
});

test("tracker: a right-swipe over a code block already scrolled fully left still closes the panel", () => {
  const swipe = loadSwipe(mobileWindow());
  const panel = fakeEl({ offsetWidth: 400 });
  const codeBlock = fakeEl({
    scrollWidth: 800,
    clientWidth: 400,
    scrollLeft: 0,
    parentElement: panel,
  });
  let closed = false;
  const tracker = swipe.createSwipeCloseTracker({
    direction: 1,
    root: () => panel,
    onClose: () => {
      closed = true;
    },
  });
  tracker.handleTouchStart(touchEvent(codeBlock, 100, 200));
  tracker.handleTouchMove(touchEvent(codeBlock, 200, 202));
  tracker.handleTouchEnd(touchEvent(codeBlock, 300, 202));
  assert.equal(closed, true);
});

test("tracker: a plain right-swipe on the chat panel (no scrollable target) closes it", () => {
  const swipe = loadSwipe(mobileWindow());
  const panel = fakeEl({ offsetWidth: 400 });
  let closed = false;
  const tracker = swipe.createSwipeCloseTracker({
    direction: 1,
    root: () => panel,
    onClose: () => {
      closed = true;
    },
  });
  const target = fakeEl({ parentElement: panel });
  tracker.handleTouchStart(touchEvent(target, 100, 200));
  tracker.handleTouchMove(touchEvent(target, 200, 202));
  tracker.handleTouchEnd(touchEvent(target, 300, 202));
  assert.equal(closed, true);
});

test("tracker: touchcancel resets state without closing", () => {
  const swipe = loadSwipe(mobileWindow());
  const root = fakeEl({ offsetWidth: 400 });
  let closed = false;
  const tracker = swipe.createSwipeCloseTracker({
    direction: -1,
    root: () => root,
    onClose: () => {
      closed = true;
    },
  });
  const target = fakeEl({ parentElement: root });
  tracker.handleTouchStart(touchEvent(target, 300, 200));
  tracker.handleTouchCancel();
  tracker.handleTouchEnd(touchEvent(target, 100, 200));
  assert.equal(closed, false);
});
