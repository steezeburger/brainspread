// Tests for the browser-side emoji shortcode engine.
//
// emoji.js is a plain IIFE that hangs itself off `window`, so it loads
// into a vm sandbox with a stub window and needs no bundler. There is
// no DOM here, which is why `renderInHtml` isn't covered — its text-node
// walk needs a real DOMParser. `replaceShortcodes` is where all the
// substitution rules live, and that part is pure.
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
  "emoji.js"
);

function loadEmoji() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), sandbox, {
    filename: SOURCE,
  });
  return sandbox.window.brainspreadEmoji;
}

const emoji = loadEmoji();

test("substitutes a known shortcode", () => {
  assert.equal(emoji.replaceShortcodes("well :joy: yes"), "well 😂 yes");
});

test("leaves an unknown shortcode exactly as typed", () => {
  assert.equal(
    emoji.replaceShortcodes("a :not_a_real_shortcode: b"),
    "a :not_a_real_shortcode: b"
  );
});

test("resolves the spellings issue #170 named", () => {
  // The author said he already types these two, so they are the
  // feature's acceptance data.
  assert.equal(emoji.replaceShortcodes(":grimace:"), "😬");
  assert.equal(emoji.replaceShortcodes(":facepalm:"), "🤦");
});

test("matches case-insensitively", () => {
  assert.equal(emoji.replaceShortcodes(":JOY:"), "😂");
});

test("renders a run of shortcodes that share a colon", () => {
  assert.equal(emoji.replaceShortcodes(":joy::joy:"), "😂😂");
  assert.equal(emoji.replaceShortcodes(":joy::joy::joy:"), "😂😂😂");
});

test("substitutes after markdown punctuation", () => {
  assert.equal(emoji.replaceShortcodes("**:joy:**"), "**😂**");
  assert.equal(emoji.replaceShortcodes("(:joy:)"), "(😂)");
});

// The opening colon has to start a word. Everything below matches the
// `:name:` shape and would be mangled without that rule.
test("leaves a time range alone", () => {
  assert.equal(emoji.replaceShortcodes("ran 10:30:45"), "ran 10:30:45");
});

test("leaves pasted lint output alone", () => {
  assert.equal(
    emoji.replaceShortcodes("src/app.py:100:8: E501"),
    "src/app.py:100:8: E501"
  );
});

test("leaves a colon-namespaced identifier alone", () => {
  assert.equal(emoji.replaceShortcodes("cache:key:ttl"), "cache:key:ttl");
  assert.equal(emoji.replaceShortcodes("core:user:read"), "core:user:read");
});

test("leaves a key::value block property alone", () => {
  // `:x:` sits between the two colons of `a::x::b`; substituting it
  // destroys the property chip Page.formatContentWithTags builds later.
  assert.equal(emoji.replaceShortcodes("a::x::b"), "a::x::b");
  assert.equal(
    emoji.replaceShortcodes("status::bug::open"),
    "status::bug::open"
  );
});

test("leaves a URL path alone", () => {
  // Substitution runs before the URL linkifier, so a mangled path would
  // end up inside the href and not just the visible text.
  assert.equal(
    emoji.replaceShortcodes("https://x.co/cache:key:ttl"),
    "https://x.co/cache:key:ttl"
  );
});

test("does not resolve inherited Object members", () => {
  for (const name of [
    ":constructor:",
    ":__proto__:",
    ":toString:",
    ":hasOwnProperty:",
    ":valueOf:",
  ]) {
    assert.equal(emoji.replaceShortcodes(name), name);
  }
});

test("passes through text with no colon at all", () => {
  assert.equal(
    emoji.replaceShortcodes("nothing to do here"),
    "nothing to do here"
  );
});

test("handles empty and nullish input", () => {
  assert.equal(emoji.replaceShortcodes(""), "");
  assert.equal(emoji.replaceShortcodes(null), null);
  assert.equal(emoji.replaceShortcodes(undefined), undefined);
});

test("render() is a no-op once the setting is turned off", () => {
  const off = loadEmoji();
  off.setEnabled(false);
  assert.equal(off.render(":joy:"), ":joy:");

  const on = loadEmoji();
  on.setEnabled(true);
  assert.equal(on.render(":joy:"), "😂");
});

test("render() defaults to on with no stored user", () => {
  assert.equal(loadEmoji().render(":joy:"), "😂");
});
