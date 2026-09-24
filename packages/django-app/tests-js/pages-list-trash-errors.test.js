// Tests for PagesListPage's restore-error message extraction (issue #122
// follow-up). apiService.request() throws for any non-2xx response —
// the restore endpoints return 400 on a validation failure — so the
// server's specific error message ("this block's page is also in
// Trash — restore the page first") only ever reaches the frontend as
// `err.payload.errors`, never as a resolved `{success:false, errors}`
// result. firstErrorMessage() must read both shapes, or a real
// validation failure silently falls back to a generic message.
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
  "PagesListPage.js"
);

function loadPagesListPage() {
  const sandbox = { window: {}, console };
  sandbox.window.window = sandbox.window;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), sandbox, {
    filename: SOURCE,
  });
  return sandbox.window.PagesListPage;
}

const { firstErrorMessage } = loadPagesListPage().methods;

test("reads the field-level message off a thrown error's .payload.errors", () => {
  const err = new Error("Request failed");
  err.payload = {
    success: false,
    data: null,
    errors: {
      block: ["This block's page is also in Trash — restore the page first."],
    },
  };

  assert.equal(
    firstErrorMessage(err, "failed to restore block"),
    "This block's page is also in Trash — restore the page first."
  );
});

test("reads errors straight off a resolved {success:false} result too", () => {
  const result = {
    success: false,
    errors: { non_field_errors: ["User is required"] },
  };

  assert.equal(
    firstErrorMessage(result, "failed to restore block"),
    "User is required"
  );
});

test("falls back when neither shape carries a usable message", () => {
  assert.equal(
    firstErrorMessage(new Error("network down"), "failed to restore block"),
    "failed to restore block"
  );
  assert.equal(
    firstErrorMessage(null, "failed to restore block"),
    "failed to restore block"
  );
  assert.equal(
    firstErrorMessage({ errors: {} }, "failed to restore block"),
    "failed to restore block"
  );
});

test("skips an error field with an empty message array", () => {
  const err = new Error("Request failed");
  err.payload = {
    errors: {
      block: [],
      non_field_errors: ["fallback message"],
    },
  };

  assert.equal(
    firstErrorMessage(err, "failed to restore block"),
    "fallback message"
  );
});
