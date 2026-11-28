/* T16: page_frame.js 纯逻辑单测（Node 运行，不依赖浏览器）。
 * 运行：node tests/test_page_frame.js   （退出码 0 = 全绿）
 */
"use strict";

const assert = require("node:assert");
const path = require("node:path");

const BSPageFrame = require(path.join(
  __dirname,
  "..",
  "app",
  "reader",
  "assets",
  "page_frame.js"
));

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log("ok - " + name);
}

const vp = (w, h) => ({ width: w, height: h });

test("default epub: page width pinned to page_width (560) on wide viewport", () => {
  const prefs = { page_width: 560, max_column_width: 920 };
  const f = BSPageFrame.computeFrame(vp(2400, 900), prefs, "epub");
  assert.strictEqual(f.width, 560);
  assert.strictEqual(f.fixed, true);
  // 视口继续变宽 → 页宽不动（固定页框，不被拉长）
  const f2 = BSPageFrame.computeFrame(vp(4000, 900), prefs, "epub");
  assert.strictEqual(f2.width, 560);
});

test("fluid (fixed_page_width=false) widens up to max_column_width", () => {
  const prefs = {
    page_width: 560,
    max_column_width: 920,
    fixed_page_width: false,
    margin_left: 56,
    margin_right: 56,
  };
  const f = BSPageFrame.computeFrame(vp(2400, 900), prefs, "epub");
  assert.strictEqual(f.fixed, false);
  assert.strictEqual(f.width, 920);
});

test("fluid shrinks to fit a narrow viewport", () => {
  const prefs = {
    page_width: 560,
    max_column_width: 920,
    fixed_page_width: false,
    margin_left: 0,
    margin_right: 0,
  };
  const f = BSPageFrame.computeFrame(vp(600, 900), prefs, "epub");
  assert.strictEqual(f.width, 600);
});

test("page height follows viewport height (fixed frame, not content)", () => {
  assert.strictEqual(BSPageFrame.computeFrame(vp(800, 700), {}, "epub").height, 700);
  assert.strictEqual(BSPageFrame.computeFrame(vp(800, 1200), {}, "epub").height, 1200);
});

test("height falls back to 640 when viewport missing", () => {
  assert.strictEqual(BSPageFrame.computeFrame(vp(800, 0), {}, "epub").height, 640);
});

test("width never drops below 320", () => {
  const f = BSPageFrame.computeFrame(vp(100, 100), { page_width: 560 }, "epub");
  assert.ok(f.width >= 320);
});

test("spread activates with enough width, deactivates when narrow", () => {
  const prefs = {
    page_mode: "spread",
    page_width: 560,
    max_column_width: 920,
    margin_left: 0,
    margin_right: 0,
  };
  const wide = BSPageFrame.computeFrame(vp(2400, 900), prefs, "epub");
  assert.strictEqual(wide.spread, true);
  assert.strictEqual(wide.maxColumnCount, 2);
  const narrow = BSPageFrame.computeFrame(vp(800, 900), prefs, "epub");
  assert.strictEqual(narrow.spread, false);
  assert.strictEqual(narrow.maxColumnCount, 1);
});

test("PDF keeps max_column_width cap and ignores the fixed flag", () => {
  const f = BSPageFrame.computeFrame(
    vp(2400, 900),
    { max_column_width: 920, fixed_page_width: false },
    "pdf"
  );
  assert.strictEqual(f.width, 920);
  assert.strictEqual(f.fixed, false);
});

test("missing prefs falls back to defaults (560 / 920)", () => {
  const f = BSPageFrame.computeFrame(vp(2400, 900), undefined, "epub");
  assert.strictEqual(f.desired, 560);
  assert.strictEqual(f.width, 560);
});

test("fixed_page_width string 'false' is treated as fluid", () => {
  const prefs = { fixed_page_width: "false", margin_left: 0, margin_right: 0 };
  const f = BSPageFrame.computeFrame(vp(2400, 900), prefs, "epub");
  assert.strictEqual(f.fixed, false);
  assert.strictEqual(f.width, 920);
});

console.log("\n" + passed + " tests passed");
