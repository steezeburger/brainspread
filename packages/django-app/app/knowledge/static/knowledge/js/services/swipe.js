// Shared "swipe to close" gesture for the mobile drawer-style sidebars
// (LeftNav's backdrop, ChatPanel's panel). Touch-only: gated behind the
// same window.innerWidth <= 768 convention the sidebars already use, plus
// a pointer/hover media check so a touchscreen laptop with a trackpad
// doesn't lose the drawer to an accidental gesture.
//
// Every listener stays passive (no preventDefault anywhere) so native
// scrolling — vertical page/sidebar scroll, horizontal scroll inside a
// code block or table — is never interrupted. The gesture is purely
// observed and, on touchend, judged against a threshold.
//
// Run with `just test-js`.

(function () {
  function isTouchViewport(win) {
    win = win || (typeof window !== "undefined" ? window : null);
    if (!win) return false;
    if (win.innerWidth > 768) return false;
    if (typeof win.matchMedia === "function") {
      try {
        return win.matchMedia("(hover: none) and (pointer: coarse)").matches;
      } catch (_) {
        // matchMedia can throw in odd embeddings; the viewport-width
        // check above already narrowed this to a small screen.
        return true;
      }
    }
    return true;
  }

  // Walks up from `target` to (but not including) `root` looking for the
  // nearest element with horizontal scroll room — a code block, table,
  // mermaid diagram, or CSV block that leaked into the swipeable area.
  function findHorizontalScrollAncestor(target, root) {
    let node = target;
    while (node && node !== root) {
      if (
        typeof node.scrollWidth === "number" &&
        typeof node.clientWidth === "number" &&
        node.scrollWidth > node.clientWidth + 1
      ) {
        return node;
      }
      node = node.parentElement || null;
    }
    return null;
  }

  // A rightward drag (dx > 0) scrolls a horizontal scroller toward its
  // start (revealing earlier content), so it only has room to consume the
  // gesture while scrollLeft > 0. A leftward drag (dx < 0) has room while
  // scrollLeft hasn't reached the end yet.
  function hasScrollRoomTowardDx(el, dx) {
    if (!el) return false;
    if (dx > 0) return el.scrollLeft > 0;
    if (dx < 0) return el.scrollLeft < el.scrollWidth - el.clientWidth - 1;
    return false;
  }

  // Pure threshold decision. direction is -1 for a leftward close (left
  // nav) or 1 for a rightward close (chat panel). Vertical-dominant drags
  // never close, matching the app's other drawer-dismiss affordances.
  function isClosingSwipe(dx, dy, direction, threshold) {
    if (Math.abs(dx) <= Math.abs(dy) * 1.5) return false;
    if (direction < 0) return dx <= -threshold;
    if (direction > 0) return dx >= threshold;
    return false;
  }

  function closeThreshold(refWidth, minPx, ratio) {
    minPx = minPx || 60;
    ratio = ratio == null ? 0.25 : ratio;
    return Math.max(minPx, (refWidth || 0) * ratio);
  }

  // Factory for the per-element gesture state a Vue component wires its
  // @touchstart/@touchmove/@touchend/@touchcancel handlers to. `options`:
  //   - direction: -1 (leftward closes) or 1 (rightward closes)
  //   - root: element, or a () => element, bounding the scroll-ancestor
  //     search and read for its offsetWidth as the threshold reference
  //   - onClose: called once the gesture crosses the threshold
  //   - threshold / thresholdRatio: passed through to closeThreshold()
  function createSwipeCloseTracker(options) {
    let tracking = false;
    let startX = 0;
    let startY = 0;
    let scrollAncestor = null;
    let resolvedAsScroll = false;

    function resolveRoot() {
      return typeof options.root === "function" ? options.root() : options.root;
    }

    return {
      handleTouchStart(e) {
        tracking = false;
        if (!isTouchViewport()) return;
        if (!e.touches || e.touches.length !== 1) return;
        const touch = e.touches[0];
        startX = touch.clientX;
        startY = touch.clientY;
        tracking = true;
        resolvedAsScroll = false;
        scrollAncestor = findHorizontalScrollAncestor(e.target, resolveRoot());
      },
      handleTouchMove(e) {
        if (!tracking || resolvedAsScroll) return;
        const touch = e.touches && e.touches[0];
        if (!touch) return;
        const dx = touch.clientX - startX;
        if (hasScrollRoomTowardDx(scrollAncestor, dx)) {
          resolvedAsScroll = true;
        }
      },
      handleTouchEnd(e) {
        if (!tracking) return;
        tracking = false;
        if (resolvedAsScroll) {
          resolvedAsScroll = false;
          return;
        }
        const touch = e.changedTouches && e.changedTouches[0];
        if (!touch) return;
        const dx = touch.clientX - startX;
        const dy = touch.clientY - startY;
        const root = resolveRoot();
        const refWidth =
          (root && root.offsetWidth) ||
          (typeof window !== "undefined" ? window.innerWidth : 0);
        const threshold = closeThreshold(
          refWidth,
          options.threshold,
          options.thresholdRatio
        );
        if (isClosingSwipe(dx, dy, options.direction, threshold)) {
          options.onClose();
        }
      },
      handleTouchCancel() {
        tracking = false;
        resolvedAsScroll = false;
      },
    };
  }

  window.brainspreadSwipe = {
    isTouchViewport,
    findHorizontalScrollAncestor,
    hasScrollRoomTowardDx,
    isClosingSwipe,
    closeThreshold,
    createSwipeCloseTracker,
  };
})();
