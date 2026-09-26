// Assertion script for js_deep_merge. Invoked as:
//   node check_assertions.js <path-to-utils.js>
'use strict';
const assert = require('node:assert/strict');

const utilsPath = process.argv[2];
if (!utilsPath) {
  console.error('usage: node check_assertions.js <path-to-utils.js>');
  process.exit(2);
}

let deepMerge;
try {
  ({ deepMerge } = require(utilsPath));
} catch (e) {
  console.error('FAIL: could not require utils.js: ' + e.message);
  process.exit(1);
}

if (typeof deepMerge !== 'function') {
  console.error('FAIL: utils.js does not export a deepMerge function');
  process.exit(1);
}

let failures = 0;

function check(name, fn) {
  try {
    fn();
    console.log('ok - ' + name);
  } catch (e) {
    failures += 1;
    console.log('FAIL - ' + name + ': ' + e.message);
  }
}

// 1. nested plain objects merge recursively
check('nested objects merge recursively', () => {
  const result = deepMerge({ a: { b: 1, c: 2 } }, { a: { b: 5 } });
  assert.deepStrictEqual(result, { a: { b: 5, c: 2 } });
});

// 2. brand new keys are simply added
check('new top-level keys are added', () => {
  const result = deepMerge({ a: 1 }, { b: 2 });
  assert.deepStrictEqual(result, { a: 1, b: 2 });
});

// 3. arrays replace wholesale, not merged index by index, and stay real arrays
check('arrays are replaced wholesale (not index-merged)', () => {
  const result = deepMerge({ a: [1, 2, 3] }, { a: [9] });
  assert.deepStrictEqual(result, { a: [9] });
  assert.strictEqual(Array.isArray(result.a), true, 'result.a should still be an Array');
});

// 4. source array replaces a target object outright
check('source array replaces a target plain object', () => {
  const result = deepMerge({ a: { x: 1 } }, { a: [9, 8] });
  assert.strictEqual(Array.isArray(result.a), true, 'result.a should be an Array');
  assert.deepStrictEqual(result.a, [9, 8]);
});

// 5. null in source overwrites target with null (not {})
check('null in source overwrites target with null', () => {
  const result = deepMerge({ a: { b: 1 } }, { a: null });
  assert.deepStrictEqual(result, { a: null });
});

// 6. null target value, object source value
check('object source overwrites a null target value', () => {
  const result = deepMerge({ a: null }, { a: { b: 1 } });
  assert.deepStrictEqual(result, { a: { b: 1 } });
});

// 7. primitive -> object and object -> primitive replacement
check('source object replaces a target primitive', () => {
  const result = deepMerge({ a: 1 }, { a: { b: 2 } });
  assert.deepStrictEqual(result, { a: { b: 2 } });
});

check('source primitive replaces a target object', () => {
  const result = deepMerge({ a: { b: 2 } }, { a: 5 });
  assert.deepStrictEqual(result, { a: 5 });
});

// 8. three levels of nesting
check('three levels of nested merging', () => {
  const result = deepMerge({ a: { b: { c: 1, d: 2 } } }, { a: { b: { c: 9 } } });
  assert.deepStrictEqual(result, { a: { b: { c: 9, d: 2 } } });
});

// 9. returns a new object, not the same target reference
check('returns a new object (not the same target reference)', () => {
  const target = { a: 1 };
  const result = deepMerge(target, { b: 2 });
  assert.notStrictEqual(result, target, 'deepMerge should return a new object, not mutate/return target');
});

// 10. inputs (including nested structures) are not mutated by the call
check('target and source are not mutated', () => {
  const target = { a: { b: 1, c: [1, 2] }, d: 4 };
  const source = { a: { b: 5, c: [9] }, e: { f: 1 } };
  const targetSnapshot = JSON.stringify(target);
  const sourceSnapshot = JSON.stringify(source);

  deepMerge(target, source);

  assert.strictEqual(JSON.stringify(target), targetSnapshot, 'target was mutated by deepMerge');
  assert.strictEqual(JSON.stringify(source), sourceSnapshot, 'source was mutated by deepMerge');
});

if (failures > 0) {
  console.log(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log('\nall checks passed');
process.exit(0);
