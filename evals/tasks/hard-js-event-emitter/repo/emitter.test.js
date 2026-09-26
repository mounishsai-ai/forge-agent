"use strict";
const assert = require("assert");
const EventEmitter = require("./emitter.js");

function run() {
  // basic on/emit
  {
    const ee = new EventEmitter();
    const calls = [];
    ee.on("greet", (name) => calls.push(name));
    const handled = ee.emit("greet", "world");
    assert.strictEqual(handled, true);
    assert.deepStrictEqual(calls, ["world"]);
  }

  // emit with no listeners returns false
  {
    const ee = new EventEmitter();
    assert.strictEqual(ee.emit("nothing"), false);
  }

  // off removes a listener
  {
    const ee = new EventEmitter();
    const calls = [];
    const fn = () => calls.push(1);
    ee.on("x", fn);
    ee.off("x", fn);
    ee.emit("x");
    assert.deepStrictEqual(calls, []);
  }

  // once fires only one time
  {
    const ee = new EventEmitter();
    let count = 0;
    ee.once("x", () => count++);
    ee.emit("x");
    ee.emit("x");
    assert.strictEqual(count, 1);
  }

  // listenerCount
  {
    const ee = new EventEmitter();
    ee.on("x", () => {});
    ee.on("x", () => {});
    assert.strictEqual(ee.listenerCount("x"), 2);
    assert.strictEqual(ee.listenerCount("y"), 0);
  }

  console.log("OK");
}

run();
