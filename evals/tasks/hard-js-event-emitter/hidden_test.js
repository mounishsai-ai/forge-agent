"use strict";
// Hidden grader script for hard-js-event-emitter. Not shipped in repo/.
// Loaded against the emitter.js in the *current working directory* (the
// grading work dir), not relative to this file's own location.
const assert = require("assert");
const path = require("path");

const emitterPath = path.join(process.cwd(), "emitter.js");
const mod = require(emitterPath);
const EventEmitter = mod.EventEmitter || mod;

function section(name, fn) {
  try {
    fn();
    console.log(`PASS: ${name}`);
  } catch (e) {
    console.log(`FAIL: ${name}`);
    console.log(e && e.stack ? e.stack : String(e));
    process.exitCode = 1;
  }
}

section("wildcard listener receives (event, ...args) for any event", () => {
  const ee = new EventEmitter();
  const seen = [];
  ee.on("*", (event, ...args) => seen.push([event, ...args]));
  ee.emit("foo", 1, 2);
  ee.emit("bar", "x");
  assert.deepStrictEqual(seen, [["foo", 1, 2], ["bar", "x"]]);
});

section("emit calls both specific and wildcard listeners", () => {
  const ee = new EventEmitter();
  const calls = [];
  ee.on("foo", (n) => calls.push(`specific:${n}`));
  ee.on("*", (event, n) => calls.push(`wild:${event}:${n}`));
  const handled = ee.emit("foo", 1);
  assert.strictEqual(handled, true);
  assert.deepStrictEqual(calls, ["specific:1", "wild:foo:1"]);
});

section("listenerCount is per exact event name, wildcard counted separately", () => {
  const ee = new EventEmitter();
  ee.on("foo", () => {});
  ee.on("foo", () => {});
  ee.on("*", () => {});
  assert.strictEqual(ee.listenerCount("foo"), 2);
  assert.strictEqual(ee.listenerCount("*"), 1);
  assert.strictEqual(ee.listenerCount("bar"), 0);
});

section("a throwing listener does not stop other listeners or propagate", () => {
  const ee = new EventEmitter();
  const calls = [];
  ee.on("x", () => {
    calls.push("first");
    throw new Error("boom");
  });
  ee.on("x", () => calls.push("second"));
  let threw = false;
  try {
    ee.emit("x");
  } catch (e) {
    threw = true;
  }
  assert.strictEqual(threw, false, "emit() must not let a listener's error propagate");
  assert.deepStrictEqual(calls, ["first", "second"]);
});

section("a throwing wildcard listener does not stop specific listeners", () => {
  const ee = new EventEmitter();
  const calls = [];
  ee.on("*", () => {
    throw new Error("boom");
  });
  ee.on("x", () => calls.push("specific-ran"));
  ee.emit("x");
  assert.deepStrictEqual(calls, ["specific-ran"]);
});

section("once listener fires exactly once and off() can remove a once listener", () => {
  const ee = new EventEmitter();
  let count = 0;
  const fn = () => count++;
  ee.once("x", fn);
  assert.strictEqual(ee.listenerCount("x"), 1);
  ee.emit("x");
  ee.emit("x");
  assert.strictEqual(count, 1);
  assert.strictEqual(ee.listenerCount("x"), 0);

  let count2 = 0;
  const fn2 = () => count2++;
  ee.once("y", fn2);
  ee.off("y", fn2);
  ee.emit("y");
  assert.strictEqual(count2, 0);
});

section("once listener is removed before being invoked (safe with recursive emit)", () => {
  const ee = new EventEmitter();
  let calls = 0;
  ee.once("x", () => {
    calls++;
    if (calls < 5) {
      ee.emit("x"); // recursive emit from inside the once handler
    }
  });
  ee.emit("x");
  assert.strictEqual(calls, 1, "once listener re-fired on a recursive emit()");
});

section("wildcard once() is removed after firing for any single event", () => {
  const ee = new EventEmitter();
  const seen = [];
  ee.once("*", (event) => seen.push(event));
  ee.emit("foo");
  ee.emit("bar");
  assert.deepStrictEqual(seen, ["foo"]);
});

section("removing a listener during emit still lets it fire for the current emit (snapshot)", () => {
  const ee = new EventEmitter();
  const calls = [];
  const second = () => calls.push("second");
  const first = () => {
    calls.push("first");
    ee.off("x", second);
  };
  ee.on("x", first);
  ee.on("x", second);
  ee.emit("x"); // both should fire this time (snapshot taken at emit start)
  assert.deepStrictEqual(calls, ["first", "second"]);
  calls.length = 0;
  ee.emit("x"); // second was removed, only... nothing left except first isn't removed
  assert.deepStrictEqual(calls, ["first"]);
});

section("adding a listener during emit does not run it during that same emit", () => {
  const ee = new EventEmitter();
  const calls = [];
  ee.on("x", () => {
    calls.push("first");
    ee.on("x", () => calls.push("added-during-emit"));
  });
  ee.emit("x");
  assert.deepStrictEqual(calls, ["first"]);
  calls.length = 0;
  ee.emit("x");
  assert.deepStrictEqual(calls.sort(), ["added-during-emit", "first"].sort());
});

section("off() during emit does not skip the listener registered right after it in the same list", () => {
  const ee = new EventEmitter();
  const calls = [];
  const a = () => {
    calls.push("a");
    ee.off("x", a); // remove self
  };
  const b = () => calls.push("b");
  const c = () => calls.push("c");
  ee.on("x", a);
  ee.on("x", b);
  ee.on("x", c);
  ee.emit("x");
  assert.deepStrictEqual(calls, ["a", "b", "c"]);
  calls.length = 0;
  ee.emit("x");
  assert.deepStrictEqual(calls, ["b", "c"]);
});

section("emit returns false when there are no listeners at all for that event", () => {
  const ee = new EventEmitter();
  assert.strictEqual(ee.emit("nothing"), false);
  ee.on("*", () => {});
  assert.strictEqual(ee.emit("nothing"), true);
});

if (process.exitCode) {
  process.exit(process.exitCode);
} else {
  console.log("ALL OK");
}
