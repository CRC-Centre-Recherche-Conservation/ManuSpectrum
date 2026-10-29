/**
 * Adds an event listener and returns the function that removes it.
 *
 * @param {EventTarget} target
 * @param {string} type
 * @param {EventListener} handler
 * @returns {() => void}
 */
export default function listen(target, type, handler) {
    target.addEventListener(type, handler);
    return () => target.removeEventListener(type, handler);
}

/**
 * Calls every stop function in the list and empties it.
 *
 * @param {Array<() => void>} stops
 */
export function stopAll(stops) {
    stops.splice(0).forEach((stop) => stop());
}
