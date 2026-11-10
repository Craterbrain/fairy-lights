// Tests for the editor page's logic. builder.html's script is run against a stub of the page, so no browser is needed.
//   node --test tests/
const { test } = require("node:test");
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");

const html = fs.readFileSync(path.join(__dirname, "..", "builder.html"), "utf8");
const script = html.match(/<script>([\s\S]*)<\/script>/)[1];
const noop = () => {};
const OFF = 254, N = 800;

const thumb = Buffer.from(new Uint8Array(N).fill(OFF)).toString("base64");
const INDEX = [
  { id: "1/christmas/tree", name: "tree", product: "1", category: "christmas", frames: 4, native: true, cropped: false, source_grid: [40, 20], thumb },
  { id: "1/animal/cat", name: "cat", product: "1", category: "animal", frames: 1, native: true, cropped: false, source_grid: [40, 20], thumb },
  { id: "1/christmas/star", name: "star", product: "1", category: "christmas", frames: 1, native: true, cropped: false, source_grid: [40, 20], thumb },
  { id: "9/gif/wide", name: "wide", product: "9", category: "gif 64×16", frames: 30, native: false, cropped: true, source_grid: [64, 16], thumb },
  { id: "9/x/plain", name: "plain", product: "9", category: "", frames: 1, native: false, cropped: false, source_grid: [20, 20], thumb },
];
const item = (id, n) => ({ name: id, speed: 70, direction: 3, frames: Array.from({ length: n }, (_, i) => new Array(N).fill(i % 2 ? 10 : OFF)) });

function page({ host } = {}) {
  const els = {};
  const mk = () => ({
    style: {}, classList: { toggle: noop, add: noop, remove: noop }, dataset: {}, value: "", checked: true, children: [], textContent: "",
    append(...a) { this.children.push(...a); }, click() { if (this.onclick) this.onclick(); }, getContext: () => ctxStub, getBoundingClientRect: () => ({ left: 0, top: 0 }),
    setPointerCapture: noop, addEventListener: noop, querySelector: () => null, parentElement: { clientWidth: 900 },
    set innerHTML(v) { this._html = v; if (v === "") this.children.length = 0; }, get innerHTML() { return this._html || ""; },
    width: 0, height: 0,
  });
  const ctxStub = new Proxy({}, {
    get: (t, k) => k === "getImageData" ? (x, y, w, h) => ({ data: new Uint8ClampedArray(w * h * 4).map((v, i) => (i % 4 === 3 ? 255 : 0)) })
      : k === "measureText" ? () => ({ width: 30 }) : noop,
    set: () => true,
  });
  const document = { getElementById: id => (els[id] ??= mk()), createElement: () => mk(), querySelectorAll: () => [], documentElement: {} };
  const fetched = [];
  const ctx = {
    atob: t => Buffer.from(t, "base64").toString("binary"), document, window: { scrollTo: noop, FairyHost: host },
    localStorage: { getItem: () => null, setItem: noop }, getComputedStyle: () => ({ getPropertyValue: () => "#222" }),
    addEventListener: noop, confirm: () => true, setInterval, clearInterval, setTimeout, clearTimeout, console, Uint8Array, JSON, Math, Array,
    fetch: async (url, opts) => {
      fetched.push([url, opts]);
      const body = url === "/api/library" ? INDEX : url.startsWith("/api/library/item") ? item(decodeURIComponent(url.split("id=")[1]), 3) : [];
      return { json: async () => body };
    },
  };
  vm.createContext(ctx); vm.runInContext(script, ctx);
  const run = c => vm.runInContext(c, ctx);
  run(`$("libq").value = ""; $("libfilter").value = "native"; $("libmulti").checked = false; $("swscope").value = "all"; undoS = []; redoS = [];`);
  return { run, els, fetched, ctx };
}

test("pen strokes, undo and redo", () => {
  const { run } = page();
  run(`colour = 10; push(); line(2, 2, 6, 2, (a, b) => { frames[cur][ix(a, b)] = colour; })`);
  assert.equal(run(`frames[0][ix(2, 2)] === 10 && frames[0][ix(6, 2)] === 10 && frames[0][ix(7, 2)] === OFF`), true);
  run(`undo()`); assert.equal(run(`frames[0][ix(2, 2)]`), OFF);
  run(`redo()`); assert.equal(run(`frames[0][ix(4, 2)]`), 10);
});

test("flood fill stops at other colours", () => {
  const { run } = page();
  run(`frames[0][ix(5, 5)] = 10; frames[0][ix(5, 6)] = 10; push(); flood(20, 10, 50)`);
  assert.equal(run(`frames[0][ix(20, 10)] === 50 && frames[0][ix(0, 0)] === 50 && frames[0][ix(5, 5)] === 10`), true);
  run(`flood(20, 10, 50)`);                                   // filling with the colour already there changes nothing
  assert.equal(run(`frames[0][ix(0, 0)]`), 50);
});

test("bounding box, move, and transparent drop", () => {
  const { run } = page();
  run(`for (let x = 2; x <= 6; x++) frames[0][ix(x, 2)] = 10`);
  assert.deepEqual(JSON.parse(run(`JSON.stringify(bbox())`)), { x: 2, y: 2, w: 5, h: 1 });
  run(`sel = bbox(); lift(); sel.x += 10; sel.y += 5; commitFloat();`);
  assert.equal(run(`frames[0][ix(12, 7)] === 10 && frames[0][ix(16, 7)] === 10 && frames[0][ix(2, 2)] === OFF`), true);
  run(`frames[0][ix(30, 3)] = 99; pasteClip({ w: 3, h: 1, data: Uint8Array.from([OFF, 7, OFF]) }, 29, 3); commitFloat();`);
  assert.equal(run(`frames[0][ix(30, 3)] === 7 && frames[0][ix(29, 3)] === OFF`), true);   // empty pixels don't erase
  assert.equal(run(`bbox() !== null`), true);
  run(`clearAll = frames[0].fill(OFF)`); assert.equal(run(`bbox()`), null);
});

test("nudging out of the frame and back loses nothing; copy, paste and delete", () => {
  const { run } = page();
  run(`frames[0][ix(12, 7)] = 10; frames[0][ix(16, 7)] = 10; sel = { x: 12, y: 7, w: 5, h: 1 }; lift(); sel.x = -2; sel.x = 12; commitFloat();`);
  assert.equal(run(`frames[0][ix(16, 7)]`), 10);
  run(`sel = { x: 12, y: 7, w: 5, h: 1 }; copySel(); pasteClip(clip, 12, 12); commitFloat();`);
  assert.equal(run(`frames[0][ix(16, 12)]`), 10);
  run(`sel = { x: 12, y: 12, w: 5, h: 1 }; deleteSel();`);
  assert.equal(run(`frames[0][ix(16, 12)] === OFF && sel === null`), true);
});

test("frame operations", () => {
  const { run } = page();
  run(`frames[0][ix(1, 1)] = 10; document.getElementById("fdup").onclick();`);
  assert.equal(run(`frames.length === 2 && cur === 1 && frames[1][ix(1, 1)] === 10`), true);
  run(`frames[1][ix(1, 1)] = OFF; frames[0][ix(2, 2)] = 20; document.getElementById("fpull").onclick();`);
  assert.equal(run(`frames[1][ix(2, 2)] === 20`), true);
  run(`document.getElementById("fnew").onclick();`);
  assert.equal(run(`frames.length === 3 && cur === 2 && frames[2].every(v => v === OFF)`), true);
  run(`document.getElementById("fleft").onclick();`); assert.equal(run(`cur`), 1);
  run(`document.getElementById("fdel").onclick();`); assert.equal(run(`frames.length`), 2);
  run(`document.getElementById("fdel").onclick(); document.getElementById("fdel").onclick();`);
  assert.equal(run(`frames.length`), 1);                                 // the last frame is cleared, never removed
});

test("scrolling text makes ceil((width + 40) / step) frames after the current one", () => {
  const { run } = page();
  run(`$("txt").value = "HI"; $("tsize").value = "11"; $("tstep").value = "2"; $("tscroll").onclick();`);
  assert.equal(run(`frames.length`), 1 + 36);
  assert.equal(run(`cur`), 1);
  assert.equal(run(`frames[1].every(v => v === OFF)`), true);           // text starts off the right edge
  assert.equal(run(`frames.slice(1).some(f => f.some(v => v !== OFF))`), true);
});

test("the payload sent to the lights", () => {
  const { run } = page();
  run(`$("speed").value = "70"; $("dir").value = "5"; $("flipx").checked = true; $("flipy").checked = false;`);
  let p = JSON.parse(run(`JSON.stringify(payload())`));
  assert.deepEqual([p.speed, p.direction, p.flipX, p.flipY, p.frames.length, p.frames[0].length], [70, 5, true, false, 1, 800]);
  run(`frames.push(new Uint8Array(N).fill(OFF))`);
  assert.equal(JSON.parse(run(`JSON.stringify(payload())`)).direction, 0);   // the effect only applies to a single picture
});

test("recolour swaps one colour in every frame or just this one", () => {
  const { run } = page();
  const setup = `frames = [0, 1, 2].map(() => new Uint8Array(N).fill(OFF)); cur = 0; undoS = [];
    frames[0][ix(1, 1)] = 10; frames[0][ix(2, 2)] = 10; frames[0][ix(3, 3)] = 20; frames[1][ix(5, 5)] = 10; frames[2][ix(6, 6)] = 10; frames[2][ix(7, 7)] = 30;`;
  run(setup);
  run(`$("swscope").value = "one"; swapFrom = 10; recolour(99)`);
  assert.equal(run(`frames[0][ix(1, 1)] === 99 && frames[0][ix(2, 2)] === 99 && frames[0][ix(3, 3)] === 20 && frames[1][ix(5, 5)] === 10`), true);
  run(`undo()`); assert.equal(run(`frames[0][ix(1, 1)]`), 10);
  run(`$("swscope").value = "all"; swapFrom = 10; recolour(77)`);
  assert.equal(run(`frames[0][ix(1, 1)] === 77 && frames[1][ix(5, 5)] === 77 && frames[2][ix(6, 6)] === 77 && frames[2][ix(7, 7)] === 30`), true);
  run(`recolour(OFF)`); assert.equal(run(`frames[0][ix(1, 1)] === OFF && frames[2][ix(7, 7)] === 30`), true);
  run(`swapFrom = null; recolour(5)`); assert.equal(run(`frames[0][ix(3, 3)]`), 20);
  run(`swapFrom = 20; recolour(20)`); assert.equal(run(`frames[0][ix(3, 3)]`), 20);
  run(`swapFrom = 200; recolour(5)`); assert.match(run(`$("swapmsg").textContent`), /No pixels/);
});

test("library: filters, category chips and loading", async () => {
  const { run, els } = page();
  await run(`libInit()`); await new Promise(r => setTimeout(r, 20));
  assert.equal(run(`lib.length`), 5);
  assert.equal(run(`libItems().length`), 3);                                     // made-for-40x20 only
  assert.equal(els.libgrid.children.length, 3);                                  // and that's what was drawn
  run(`$("libfilter").value = "all"`); assert.equal(run(`libItems().length`), 5);
  run(`$("libfilter").value = "native"; $("libmulti").checked = true`); assert.equal(run(`libItems().length`), 1);
  run(`$("libmulti").checked = false; $("libq").value = "tree"`); assert.equal(run(`libItems().length`), 1);
  run(`$("libq").value = ""; libCat = "christmas"`); assert.equal(run(`libItems().length`), 2);
  run(`libChips()`);
  assert.deepEqual(els.libchips.children.map(b => b.textContent), ["All 3", "animal 1", "christmas 2"]);
  run(`$("libfilter").value = "all"; libCat = "uncategorised"; libChips()`);
  assert.ok(els.libchips.children.some(b => b.textContent === "uncategorised 1"));
  run(`libCat = "gone"; libChips()`); assert.equal(run(`libCat`), "");               // a category that no longer matches resets
  run(`libRender(false)`); assert.equal(els.libgrid.children.length, 5);
  assert.match(els.libcount.textContent, /5 of 5/);

  run(`frames[0][ix(1, 1)] = 5; undoS = []`);
  await run(`(async () => { loadLibrary(await api("/api/library/item?id=1%2Fchristmas%2Ftree")); })()`); await new Promise(r => setTimeout(r, 20));
  assert.equal(run(`frames.length`), 3);
  assert.equal(run(`$("speed").value`), 70);
  run(`undo()`); assert.equal(run(`frames.length === 1 && frames[0][ix(1, 1)] === 5`), true);   // undo brings the old work back
});

test("api() talks to the native bridge when the page runs inside the Android app", async () => {
  const calls = [];
  const host = { call: (p, b) => { calls.push([p, b]); return JSON.stringify(p === "/api/library" || p === "/api/projects" ? [] : { ok: true, p }); } };
  const { run, fetched } = page({ host });
  calls.length = 0; fetched.length = 0;                                                  // forget the page's own start-up calls
  const r = await run(`api("/api/save", { name: "x" })`);
  assert.deepEqual(r, { ok: true, p: "/api/save" });
  assert.deepEqual(calls[0], ["/api/save", '{"name":"x"}']);
  await run(`api("/api/state")`); assert.equal(calls[1][1], "");
  assert.equal(fetched.length, 0);                                                       // no network call at all
});

test("api() uses fetch in a browser", async () => {
  const { run, fetched } = page();
  fetched.length = 0;
  await run(`api("/api/power", { on: true })`);
  assert.equal(fetched[0][0], "/api/power"); assert.equal(fetched[0][1].method, "POST");
  await run(`api("/api/state")`); assert.equal(Object.keys(fetched[1][1]).length, 0);              // a plain GET: no method, no body
});
