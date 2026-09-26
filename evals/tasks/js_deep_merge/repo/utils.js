/**
 * Recursively merge `source` into `target` and return the merged object.
 *
 * NOTE: this implementation has known bugs (nested objects, arrays, null
 * handling, and mutation of inputs) — see the task description.
 */
function deepMerge(target, source) {
  for (const key in source) {
    const sourceVal = source[key];
    if (typeof sourceVal === "object") {
      if (!target[key]) {
        target[key] = {};
      }
      target[key] = deepMerge(target[key], sourceVal);
    } else {
      target[key] = sourceVal;
    }
  }
  return target;
}

module.exports = { deepMerge };
