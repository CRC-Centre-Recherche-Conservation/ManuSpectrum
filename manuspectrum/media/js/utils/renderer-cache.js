/**
 * Shared renderer configuration cache.
 *
 * Deduplicates concurrent fetch calls to `/renderer/{uuid}` by caching
 * the Promise itself. Multiple consumers calling getRendererConfig()
 * with the same ID before the first request resolves will share a
 * single HTTP request.
 */
import ko from 'knockout';

const cache = {};

/**
 * Returns the renderer JSON for the given ID.
 * Reuses an in-flight or resolved Promise when available.
 *
 * @param {string} rendererId - UUID of the renderer
 * @returns {Promise<Object>} - the parsed renderer JSON
 */
export function getRendererConfig(rendererId) {
    if (!cache[rendererId]) {
        cache[rendererId] = fetch('/renderer/' + rendererId)
            .then(function (res) {
                if (!res.ok) throw new Error('Renderer fetch failed: ' + res.status);
                return res.json();
            })
            .catch(function (err) {
                delete cache[rendererId];
                throw err;
            });
    }
    return cache[rendererId];
}

/**
 * Invalidates the cache for a specific renderer ID.
 * Call this before refreshing after a POST/DELETE of config.
 *
 * @param {string} rendererId - UUID of the renderer
 */
export function invalidate(rendererId) {
    delete cache[rendererId];
}

/**
 * Safely parse parsingOverrides from tile data.
 * Handles plain objects (normal case), JSON strings (legacy/edge-case),
 * and falsy values.
 *
 * @param {*} raw - the raw value from ko.unwrap(node.parsingOverrides)
 * @returns {Object} - parsed overrides or empty object
 */
export function parseOverrides(raw) {
    if (!raw) return {};
    if (typeof raw === 'string') {
        try { return JSON.parse(raw); } catch { return {}; }
    }
    if (typeof raw === 'object') return ko.toJS(raw);
    return {};
}
