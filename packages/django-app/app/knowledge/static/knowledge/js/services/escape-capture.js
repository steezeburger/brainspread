// Shared Vue mixin for modals/popovers that must close on Escape even
// when focus has drifted off any focusable element inside them.
//
// A template `@keydown` binding on a modal's own root only fires while
// a descendant of that element has focus. Clicking a non-focusable
// part of the modal (a heading, a paragraph, the backdrop itself)
// blurs focus without moving it back in, silently breaking Escape —
// the keystroke then falls through to app.js's document-level bubble
// handler, which closes the left nav / chat panel instead of the
// modal. Binding the handler directly on `document` in the capture
// phase makes it focus-independent and guarantees it runs, and can
// call stopPropagation(), before that bubble-phase listener ever sees
// the event.
//
// A component opts in with:
//   mixins: [window.brainspreadEscapeCaptureMixin],
//   methods: {
//     escapeCaptureFlag() { return "isOpen"; },       // data/computed name that means "open"
//     escapeCaptureHandlerName() { return "onKeydown"; }, // method to call for every captured keydown
//   }
//
// The named handler is called for every keydown while open — not just
// Escape — so a component that also drives other shortcuts while open
// (e.g. Enter-to-confirm) keeps doing its own key filtering exactly as
// before; this mixin only owns the watch → toggle → cleanup wiring.
//
// Loaded before the components in base.html, so it's there by the
// time a component's options object is built.
window.brainspreadEscapeCaptureMixin = {
  created() {
    this._escapeCaptureListener = (event) => {
      this[this.escapeCaptureHandlerName()](event);
    };
  },

  mounted() {
    const flag = this.escapeCaptureFlag();
    this._unwatchEscapeCapture = this.$watch(flag, (open) => {
      this._toggleEscapeCapture(!!open);
    });
    if (this[flag]) this._toggleEscapeCapture(true);
  },

  beforeUnmount() {
    this._toggleEscapeCapture(false);
    if (this._unwatchEscapeCapture) this._unwatchEscapeCapture();
  },

  methods: {
    _toggleEscapeCapture(open) {
      if (open) {
        document.addEventListener("keydown", this._escapeCaptureListener, true);
      } else {
        document.removeEventListener(
          "keydown",
          this._escapeCaptureListener,
          true
        );
      }
    },
  },
};
