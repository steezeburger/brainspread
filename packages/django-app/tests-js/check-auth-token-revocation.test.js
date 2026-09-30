// Tests for isConfirmedInvalidToken(), the helper checkAuth() uses to
// decide whether a failed /me/ call justifies calling the backend logout
// endpoint (issue #250).
//
// The DRF auth token is a single row shared by every device and by MCP
// (Token has `user = OneToOneField(...)`), and LogoutCommand deletes that
// row outright. Before this fix, checkAuth() called handleLogout() (which
// hits that endpoint) on ANY /me/ failure - a network blip, a transient
// 5xx, anything - silently signing out every other device and MCP. Only a
// confirmed 401 (a genuinely invalid/expired token, per DRF's
// TokenAuthentication + IsAuthenticated) should trigger that destructive
// call; everything else must fall back to a local-only "logged out" UI.
//
// app.js isn't a self-contained module - it calls Vue.createApp(...) and
// touches window.apiService/document/navigator at load time - so this
// loads only the leading slice of the file up through the helper's
// definition, the same way emoji.test.js loads a plain window-attached
// function without needing the rest of the app to boot.
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
  "app.js"
);

function loadIsConfirmedInvalidToken() {
  const source = fs.readFileSync(SOURCE, "utf8");
  const marker = "window.isConfirmedInvalidToken = isConfirmedInvalidToken;";
  const markerIndex = source.indexOf(marker);
  assert.ok(
    markerIndex !== -1,
    "expected app.js to still define and export isConfirmedInvalidToken"
  );
  const fragment = source.slice(0, markerIndex + marker.length);

  // The sliced fragment still starts with `const { createApp } = Vue;`
  // even though createApp() is never called within the slice, so Vue
  // needs a stub destructuring target.
  const sandbox = { window: {}, Vue: { createApp: () => {} } };
  vm.createContext(sandbox);
  vm.runInContext(fragment, sandbox, { filename: SOURCE });
  return sandbox.window.isConfirmedInvalidToken;
}

const isConfirmedInvalidToken = loadIsConfirmedInvalidToken();

test("a genuine 401 is a confirmed invalid token", () => {
  const error = new Error("Request failed");
  error.status = 401;

  assert.equal(isConfirmedInvalidToken(error), true);
});

test("a transient 5xx is NOT a confirmed invalid token", () => {
  const error = new Error("Request failed");
  error.status = 500;

  assert.equal(isConfirmedInvalidToken(error), false);
});

test("a network error with no status is NOT a confirmed invalid token", () => {
  const error = new Error("Failed to fetch");

  assert.equal(isConfirmedInvalidToken(error), false);
});

test("other 4xx statuses are NOT treated as a confirmed invalid token", () => {
  const error = new Error("Request failed");
  error.status = 403;

  assert.equal(isConfirmedInvalidToken(error), false);
});

test("a null/undefined error is NOT a confirmed invalid token", () => {
  assert.equal(isConfirmedInvalidToken(null), false);
  assert.equal(isConfirmedInvalidToken(undefined), false);
});
