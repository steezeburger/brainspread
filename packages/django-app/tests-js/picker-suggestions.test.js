// Tests for the move-to-page picker's tag-first suggestions (issue #195).
//
// AppModals.js hangs `suggestedPagesFromBlockTags` and the `AppModals`
// component options off `window`, so it loads into a vm sandbox with a
// stub window and needs no bundler. The picker methods under test are
// pure functions of (opts, query) — they read `this.active.opts` and
// write `this.picker*` — so they're exercised against a hand-built
// `this` rather than a mounted component. The template/render half
// (the TAGGED badge) isn't covered here; it needs a real DOM.
//
// Run with `just test-js`.

const test = require("node:test");
const nodeAssert = require("node:assert/strict");
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
  const sandbox = { window: {}, console, setTimeout, clearTimeout };
  sandbox.window.window = sandbox.window;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(SOURCE, "utf8"), sandbox, {
    filename: SOURCE,
  });
  return sandbox.window;
}

const { suggestedPagesFromBlockTags, AppModals } = loadAppModals();
const methods = AppModals.methods;

// Arrays built inside the vm have a different Array.prototype, so
// deepStrictEqual's prototype check fails on otherwise-equal values.
// Compare by value instead.
const assert = {
  equal: nodeAssert.equal,
  deepEqual: (actual, expected, message) =>
    nodeAssert.deepEqual(JSON.parse(JSON.stringify(actual)), expected, message),
};

// The slice of the component the picker methods actually touch.
function picker(opts) {
  return {
    active: { opts },
    pickerResults: [],
    pickerSuggestedUuids: [],
    pickerSelectedIndex: 0,
    _suggestedPages: methods._suggestedPages,
    _applyPickerResults: methods._applyPickerResults,
  };
}

// One entry of BlockData["tags"], as Block.to_dict() serializes it.
const tag = (uuid, name, title, pageType = "page") => ({
  name,
  uuid,
  title,
  page_type: pageType,
  color: "#007bff",
});

const page = (uuid, title, slug, pageType = "page") => ({
  uuid,
  title,
  slug,
  page_type: pageType,
});

test("a block's tags become page-shaped suggestions", () => {
  assert.deepEqual(
    suggestedPagesFromBlockTags([{ tags: [tag("u1", "recipes", "Recipes")] }]),
    [{ uuid: "u1", title: "Recipes", slug: "recipes", page_type: "page" }]
  );
});

test("bulk move ranks a page tagged by more of the blocks first", () => {
  const out = suggestedPagesFromBlockTags([
    { tags: [tag("u1", "alpha", "Alpha")] },
    { tags: [tag("u2", "beta", "Beta")] },
    { tags: [tag("u2", "beta", "Beta")] },
  ]);
  assert.deepEqual(
    out.map((p) => p.slug),
    ["beta", "alpha"]
  );
});

test("equal counts tie-break by title, not by selection order", () => {
  // Selecting the #zebra block first must not outrank #apple.
  const out = suggestedPagesFromBlockTags([
    { tags: [tag("u1", "zebra", "Zebra")] },
    { tags: [tag("u2", "apple", "Apple")] },
  ]);
  assert.deepEqual(
    out.map((p) => p.title),
    ["Apple", "Zebra"]
  );
});

test("title falls back to the slug when a tag carries no title", () => {
  const out = suggestedPagesFromBlockTags([
    { tags: [{ uuid: "u1", name: "recipes" }] },
  ]);
  assert.equal(out[0].title, "recipes");
  assert.equal(out[0].page_type, "page");
});

test("malformed block payloads yield no suggestions instead of throwing", () => {
  assert.deepEqual(suggestedPagesFromBlockTags(null), []);
  assert.deepEqual(suggestedPagesFromBlockTags([null, undefined]), []);
  assert.deepEqual(suggestedPagesFromBlockTags([{}]), []);
  assert.deepEqual(suggestedPagesFromBlockTags([{ tags: null }]), []);
  // A block created this session before the tags round-trip.
  assert.deepEqual(suggestedPagesFromBlockTags([{ content: "hi" }]), []);
  // A tag with no uuid can't address a page, so it can't be a suggestion.
  assert.deepEqual(
    suggestedPagesFromBlockTags([{ tags: [{ name: "x", color: "#fff" }] }]),
    []
  );
});

test("suggestions sit above the server rows and dedupe against them", () => {
  const p = picker({ suggestedPages: [page("u1", "Recipes", "recipes")] });
  p._applyPickerResults(p._suggestedPages(""), [
    page("u9", "Journal", "journal"),
    page("u1", "Recipes", "recipes"), // the tag page is in recents too
  ]);
  assert.deepEqual(
    p.pickerResults.map((row) => row.title),
    ["Recipes", "Journal"]
  );
  assert.deepEqual(p.pickerSuggestedUuids, ["u1"]);
  assert.equal(p.pickerSelectedIndex, 0);
});

test("suggestions outrank the pinned daily on the empty query", () => {
  const p = picker({ suggestedPages: [page("u1", "Recipes", "recipes")] });
  p._applyPickerResults(p._suggestedPages(""), [
    page("d1", "2026-08-24", "2026-08-24", "daily"),
  ]);
  assert.deepEqual(
    p.pickerResults.map((row) => row.title),
    ["Recipes", "2026-08-24"]
  );
});

test("typing hands the list to the search endpoint", () => {
  // Once the user states what they want, a caller-supplied row must not
  // sit pre-selected above the results they asked for.
  const p = picker({
    suggestedPages: [
      page("u1", "Recipes", "recipes"),
      page("u2", "Cooking", "cooking"),
    ],
  });
  assert.deepEqual(p._suggestedPages("rec"), []);
  assert.deepEqual(p._suggestedPages("r"), []);
  assert.deepEqual(p._suggestedPages("recipes"), []);
  // Whitespace is not a query.
  assert.deepEqual(
    p._suggestedPages("   ").map((row) => row.slug),
    ["recipes", "cooking"]
  );
});

test("a typed query keeps the server's own ordering", () => {
  const p = picker({ suggestedPages: [page("u1", "Recipes", "recipes")] });
  p._applyPickerResults(p._suggestedPages("rec"), [
    page("u7", "Rec Room", "rec-room"),
    page("u1", "Recipes", "recipes"),
  ]);
  assert.deepEqual(
    p.pickerResults.map((row) => row.title),
    ["Rec Room", "Recipes"]
  );
  assert.deepEqual(p.pickerSuggestedUuids, []);
});

test("a failed search with a query leaves nothing selected", () => {
  // The confirm button keys off index -1, so Enter can't move the block
  // somewhere the user never picked.
  const p = picker({ suggestedPages: [page("u1", "Workout", "workout")] });
  p._applyPickerResults(p._suggestedPages("work"), []);
  assert.deepEqual(p.pickerResults, []);
  assert.equal(p.pickerSelectedIndex, -1);
});

test("a failed recents fetch still offers the block's own tags", () => {
  // Nothing was typed, so there's no user intent to drop on the floor,
  // and the suggestions came from the block rather than the network.
  const p = picker({ suggestedPages: [page("u1", "Recipes", "recipes")] });
  p._applyPickerResults(p._suggestedPages(""), []);
  assert.deepEqual(
    p.pickerResults.map((row) => row.title),
    ["Recipes"]
  );
  assert.equal(p.pickerSelectedIndex, 0);
});

test("pageType filters suggestions the same way it filters the server rows", () => {
  const p = picker({
    pageType: "page",
    suggestedPages: [
      page("u1", "Recipes", "recipes"),
      page("u2", "2026-08-21", "2026-08-21", "daily"),
    ],
  });
  assert.deepEqual(
    p._suggestedPages("").map((row) => row.slug),
    ["recipes"]
  );
});

test("a uuid repeated in suggestedPages is listed once", () => {
  const p = picker({
    suggestedPages: [
      page("u1", "Recipes", "recipes"),
      page("u1", "Recipes", "recipes"),
    ],
  });
  assert.equal(p._suggestedPages("").length, 1);
});

test("an empty picker disables confirm", () => {
  const p = picker({ suggestedPages: [] });
  p._applyPickerResults([], []);
  assert.deepEqual(p.pickerResults, []);
  assert.equal(p.pickerSelectedIndex, -1);
});
