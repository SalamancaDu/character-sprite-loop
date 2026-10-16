// Run with node --test scripts/test_preview.cjs. These are logic checks, not browser rendering tests.
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const template = readFileSync(path.join(__dirname, "../assets/preview.html"), "utf8");
const source = template.match(/<script>\s*([\s\S]*?)<\/script>/)[1];

async function harness(failedImage = false) {
  const data = { frames: Array.from({ length: 25 }, (_, i) => `frames/frame_${String(i + 1).padStart(2, "0")}.png`),
    width: 360, height: 360, frameMs: 60 };
  const elements = new Map();
  const makeElement = () => ({ textContent: "", disabled: true, hidden: true, dataset: {}, listeners: new Map(),
    addEventListener(name, callback) { this.listeners.set(name, callback); },
    emit(name, event = {}) { this.listeners.get(name)(event); } });
  for (const match of template.matchAll(/id="([^"]+)"/g)) elements.set(match[1], makeElement());
  elements.get("frame-data").textContent = JSON.stringify(data);
  const document = Object.assign(makeElement(), { hidden: false, getElementById: id => elements.get(id) });
  let time = 0;
  let serial = 0;
  const callbacks = new Map();
  class TestImage {
    set src(value) { this.path = value; queueMicrotask(() => failedImage ? this.onerror() : this.onload()); }
    get src() { return this.path; }
  }
  vm.runInNewContext(source, {
    document, Image: TestImage, performance: { now: () => time },
    requestAnimationFrame(callback) { callbacks.set(++serial, callback); return serial; },
    cancelAnimationFrame(id) { callbacks.delete(id); },
  }, { filename: "preview.html" });
  await new Promise(resolve => setImmediate(resolve));
  return { data, document, element: id => elements.get(id),
    click: id => elements.get(id).emit("click"),
    advance(value) {
      time = value;
      const pending = [...callbacks.values()];
      callbacks.clear();
      pending.forEach(callback => callback(time));
    } };
}

test("source PNG order and frame duration continue across two complete loops", async () => {
  const h = await harness();
  assert.equal(h.element("toggle").disabled, false);
  assert.equal(h.element("frame-counter").textContent, "1 / 25");
  h.click("toggle");
  assert.equal(h.element("toggle").textContent, "暂停");
  h.advance(59);
  assert.equal(h.element("frame-counter").textContent, "1 / 25");
  for (let step = 1; step <= 50; step++) {
    h.advance(step * 60);
    assert.equal(h.element("sprite").src, h.data.frames[step % 25]);
    assert.equal(h.element("frame-counter").textContent, `${step % 25 + 1} / 25`);
  }
  // Delayed callbacks sample the original clock; they do not slow down the timeline.
  h.advance(3330);
  assert.equal(h.element("frame-counter").textContent, "6 / 25");
  h.click("toggle");
  h.advance(9000);
  assert.equal(h.element("frame-counter").textContent, "6 / 25");
  assert.equal(h.element("toggle").textContent, "播放");
  h.click("toggle");
  h.advance(9060);
  assert.equal(h.element("frame-counter").textContent, "7 / 25");
});

test("stepping wraps both ways, pauses playback, and backgrounds leave source unchanged", async () => {
  const h = await harness();
  h.click("previous");
  assert.equal(h.element("frame-counter").textContent, "25 / 25");
  h.click("next");
  assert.equal(h.element("frame-counter").textContent, "1 / 25");
  h.click("toggle");
  h.click("next");
  assert.equal(h.element("toggle").textContent, "播放");
  h.advance(600);
  assert.equal(h.element("frame-counter").textContent, "2 / 25");
  const sourcePath = h.element("sprite").src;
  for (const value of ["dark", "checker", "light"]) {
    h.element("background").emit("change", { target: { value } });
    assert.equal(h.element("stage").dataset.background, value);
    assert.equal(h.element("sprite").src, sourcePath);
  }
  h.click("toggle");
  h.document.hidden = true;
  h.document.emit("visibilitychange");
  h.advance(1200);
  assert.equal(h.element("toggle").textContent, "播放");
  assert.equal(h.element("frame-counter").textContent, "2 / 25");
});

test("missing PNG reports the relative path and keeps playback disabled", async () => {
  const h = await harness(true);
  assert.equal(h.element("status").textContent, "加载失败");
  assert.equal(h.element("error").hidden, false);
  assert.match(h.element("error").textContent, /frames\/frame_01\.png/);
  for (const id of ["previous", "toggle", "next"]) assert.equal(h.element(id).disabled, true);
});
