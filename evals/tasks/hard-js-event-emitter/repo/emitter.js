"use strict";

/**
 * A small typed-ish event emitter.
 *
 * new EventEmitter()
 *
 * on(event, listener)
 *   Register `listener` for `event`. `event` can be the string '*', which is
 *   a wildcard: it fires on every emit() call, regardless of the event name,
 *   and receives (event, ...args) - i.e. the event name is prepended to the
 *   original emit() arguments. A regular (non-wildcard) listener just
 *   receives (...args), the original emit() arguments.
 *   Returns `this` (for chaining).
 *
 * once(event, listener)
 *   Like on(), but the listener is automatically removed the first time it
 *   would be invoked for that event (including if `event` is '*' - a
 *   wildcard once() listener is removed after firing once for ANY event).
 *   The listener is removed even if it throws.
 *   Returns `this`.
 *
 * off(event, listener)
 *   Removes a listener previously added with on() or once() under that
 *   exact `event` name (matched by function reference/identity). No-op if
 *   not found. Returns `this`.
 *
 * emit(event, ...args)
 *   Calls every listener registered for `event` (in registration order)
 *   with (...args), then every wildcard ('*') listener with (event, ...args).
 *   - Error isolation: if a listener throws, emit() catches it, does not
 *     let it propagate, and continues calling the remaining listeners.
 *   - Snapshot semantics: emit() dispatches to the listeners that were
 *     registered at the moment emit() was called. on()/off()/once() calls
 *     made by a listener *during* this emit() must not affect which
 *     listeners are called (or how many times) during this same emit()
 *     call - added listeners run on the next emit(), removed listeners
 *     still run for the remainder of the current emit().
 *   - Returns true if at least one listener (regular or wildcard) was
 *     invoked for this event, false otherwise.
 *
 * listenerCount(event)
 *   Returns the number of listeners currently registered under that exact
 *   event name. listenerCount('*') returns the number of wildcard
 *   listeners; it does NOT include listeners registered under specific
 *   event names, and listenerCount('foo') does NOT include wildcard
 *   listeners.
 */
class EventEmitter {
  constructor() {
    throw new Error("not implemented");
  }

  on(event, listener) {
    throw new Error("not implemented");
  }

  once(event, listener) {
    throw new Error("not implemented");
  }

  off(event, listener) {
    throw new Error("not implemented");
  }

  emit(event, ...args) {
    throw new Error("not implemented");
  }

  listenerCount(event) {
    throw new Error("not implemented");
  }
}

module.exports = EventEmitter;
module.exports.EventEmitter = EventEmitter;
