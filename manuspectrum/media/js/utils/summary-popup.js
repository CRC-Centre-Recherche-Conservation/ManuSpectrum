/**
 * Page cache and popup binders for the `ms-summary-popup` component.
 *
 * The cache is module-level and refcounted because both surfaces destroy and
 * rebuild the component around a request that is still useful. `map-popup.htm`
 * wraps its body in `<!-- ko if: active -->`, so stepping left or right through
 * the features of one map click disposes the component and builds a new one —
 * often for a resource a previous popup already asked for. A per-instance
 * AbortController would cancel a request the next instance is about to need, so
 * `acquireSummary` hands out a shared promise and counts its readers: only the
 * reader that leaves last, while the request is still in flight, aborts it.
 *
 * Entries are keyed by language as well as by id: the payload carries localized
 * labels, and Arches serves both languages from the same page load.
 *
 * The cache is the only global this module owns, and it is bounded: an entry
 * that settled is kept for the next popup, up to `MAX_ENTRIES`, oldest first
 * out. Everything else — every listener a binder adds on a popup — is removed
 * in that popup's own close handler.
 */

import ko from 'knockout';
import L from 'leaflet';
import arches from 'arches';

/** Resolved entries kept for the next popup; the oldest goes first. */
const MAX_ENTRIES = 50;

/** Feature counts a map click warms in one request; outside, warming is off. */
const WARM_MIN_IDS = 2;
const WARM_MAX_IDS = 10;

/** `${lang}|${resourceid}` -> `{promise, controller, refs}`. */
const cache = new Map();

/** A settled entry holds no controller, which is also how "pending" is read. */
const isPending = (entry) => Boolean(entry && entry.controller);

const currentLanguage = () => document.documentElement.lang || 'en';

const cacheKey = (id) => `${currentLanguage()}|${id}`;

const isAbort = (error) => Boolean(error) && error.name === 'AbortError';

/** A promise that never settles: an aborted request has no reader left. */
const never = () => new Promise(() => {});

/**
 * The summary endpoint for one resource.
 *
 * `arches.urls.root` already carries the language prefix the route needs.
 */
export function summaryUrl(id) {
    return `${arches.urls.root}api/summary/${encodeURIComponent(id)}`;
}

function batchUrl(ids) {
    return `${arches.urls.root}api/summary?ids=${ids.join(',')}`;
}

/**
 * One request, resolved to the status the component renders.
 *
 * 403 and 404 are answers, not failures: they say the reader may not see the
 * resource, or that it is gone. Anything else — another refusal, a dropped
 * connection, a body that is not JSON — is `network`, which the component
 * offers to retry. An abort resolves to nothing at all: it happens only once
 * the entry has no reader, and a rejection there would surface as an
 * unhandled one.
 */
async function requestSummary(id, signal) {
    let response;
    try {
        response = await fetch(summaryUrl(id), {
            credentials: 'same-origin',
            headers: { Accept: 'application/json' },
            signal,
        });
    } catch (error) {
        return isAbort(error) ? never() : { status: 'network' };
    }
    if (response.status === 403) return { status: 'forbidden' };
    if (response.status === 404) return { status: 'notfound' };
    if (!response.ok) return { status: 'network' };
    try {
        return { status: 'ok', data: await response.json() };
    } catch (error) {
        return isAbort(error) ? never() : { status: 'network' };
    }
}

/** Drop settled entries, oldest first, until the cache is back under the cap. */
function trimCache() {
    while (cache.size > MAX_ENTRIES) {
        const stale = [...cache.keys()].find((key) => !isPending(cache.get(key)));
        if (stale === undefined) return;
        cache.delete(stale);
    }
}

/**
 * Take a reference on the summary of one resource.
 *
 * Returns `{promise, release}`. `promise` resolves to `{status: 'ok', data}` or
 * to `{status: 'forbidden'|'notfound'|'network'}`, and never rejects. `release`
 * is idempotent and must be called from the reader's `dispose()`: it drops the
 * reference and, when it was the last one on a request still in flight, aborts
 * it and forgets the entry. A settled entry survives its readers.
 */
export function acquireSummary(id) {
    const key = cacheKey(id);
    let entry = cache.get(key);
    if (!entry) {
        const controller = new AbortController();
        entry = { promise: null, controller, refs: 0 };
        entry.promise = requestSummary(id, controller.signal).then((result) => {
            entry.controller = null;
            trimCache();
            return result;
        });
        cache.set(key, entry);
        trimCache();
    }
    entry.refs += 1;

    let released = false;
    const release = () => {
        if (released) return;
        released = true;
        entry.refs -= 1;
        if (entry.refs > 0 || !isPending(entry)) return;
        entry.controller.abort();
        if (cache.get(key) === entry) cache.delete(key);
    };

    return { promise: entry.promise, release };
}

/**
 * Forget the settled summary of one resource.
 *
 * A retry has to reach the server again, and a settled entry answers from the
 * page instead — including one that settled on a refusal, which is exactly the
 * entry a retry exists to replace. A pending entry is left alone: its readers
 * are still waiting on the request it holds.
 */
export function invalidateSummary(id) {
    const key = cacheKey(id);
    const entry = cache.get(key);
    if (entry && !isPending(entry)) cache.delete(key);
}

/**
 * Warm the cache with the resources one map click is about to offer.
 *
 * Only for a handful of features: a single one is fetched by the popup itself,
 * and past ten the endpoint refuses anyway. Entries the page already holds are
 * left alone — a warm-up never replaces an answer a reader is waiting on — and
 * a failed warm-up is silent, since the click that follows fetches for itself.
 */
export function warmSummaryCache(ids) {
    if (!Array.isArray(ids) || ids.length < WARM_MIN_IDS || ids.length > WARM_MAX_IDS) {
        return;
    }
    if (ids.every((id) => cache.has(cacheKey(id)))) return;

    fetch(batchUrl(ids), {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
    })
        .then((response) => (response.ok ? response.json() : null))
        .then((payload) => {
            const summaries = (payload && payload.summaries) || {};
            Object.keys(summaries).forEach((id) => {
                const key = cacheKey(id);
                if (cache.has(key)) return;
                cache.set(key, {
                    promise: Promise.resolve({ status: 'ok', data: summaries[id] }),
                    controller: null,
                    refs: 0,
                });
            });
            trimCache();
        })
        .catch(() => {
            // A warm-up is an optimisation; the popup fetches on its own.
        });
}

/**
 * Hand focus to a popup that just opened.
 *
 * The card is a `role="dialog"` with nothing focusable of its own when the
 * payload has no link, so it takes the tab index a programmatic focus needs.
 */
function focusPopup(element) {
    element.tabIndex = -1;
    element.focus();
}

/** Give focus back to what opened the popup, unless the page lost it since. */
function restoreFocus(element) {
    if (element && typeof element.focus === 'function' && document.contains(element)) {
        element.focus();
    }
}

/**
 * Give a Mapbox popup the teardown and the keyboard Arches does not give it.
 *
 * Called from the popup provider's `processData`, which runs once the popup
 * exists, and returns its argument so it can sit in that pipeline. Arches never
 * runs `ko.cleanNode` on a popup, so without this the component's `dispose()`
 * never fires and the reference it holds on the cache is never released.
 * Mapbox also ships no Escape handler and an English close label, and moves
 * focus neither into the card nor back to the feature that opened it. The
 * listener, the label and the focus are all undone in the popup's own `close`
 * handler, and the popup is marked so a second pass adds nothing.
 */
export function attachMapboxPopupCleanup(data) {
    const popup = data?.popupFeatures?.[0]?.mapCard?.popup;
    const content = popup?._content;
    if (!content || popup._msSummaryCleanup) return data;
    popup._msSummaryCleanup = true;

    const opener = document.activeElement;

    const onKeydown = (event) => {
        if (event.key === 'Escape' || event.key === 'Esc') popup.remove();
    };
    content.addEventListener('keydown', onKeydown);

    const closeButton = content.querySelector('.mapboxgl-popup-close-button');
    const closeLabel = arches.translations?.summaryClose;
    if (closeButton && closeLabel) closeButton.setAttribute('aria-label', closeLabel);

    popup.on('close', () => {
        content.removeEventListener('keydown', onKeydown);
        ko.cleanNode(content);
        restoreFocus(opener);
    });

    focusPopup(content);

    return data;
}

/**
 * Show the summary of an annotated resource in a Leaflet popup.
 *
 * Passed as `onEachFeature` to the IIIF viewer, which then skips its own popup
 * branch. The host is rebuilt on every open because Leaflet reuses the popup
 * container, which would orphan the bindings of the previous open, and it is
 * cleaned on every close — `bindPopup` closes the popup when the annotation
 * layer is rebuilt, so a canvas change releases the cache reference too.
 *
 * Focus moves into the card on every open and back to whatever opened it on
 * every close.
 */
export function bindLeafletSummaryPopup(feature, layer) {
    const properties = feature?.properties || {};
    if (!properties.resourceId) return;

    let host = null;
    let opener = null;
    const popup = L.popup({
        maxWidth: 360,
        minWidth: 260,
        className: 'ms-summary-popup-shell',
    });

    popup.on('add', () => {
        opener = document.activeElement;
        host = document.createElement('div');
        popup.setContent(host);
        ko.applyBindingsToNode(host, {
            component: {
                name: 'ms-summary-popup',
                params: {
                    resourceId: properties.resourceId,
                    graphName: properties.graphName,
                    surface: 'iiif',
                    context: {
                        tileId: properties.tileId,
                        nodeId: properties.nodeId,
                        canvas: properties.canvas,
                    },
                },
            },
        });
        focusPopup(host);
    });

    popup.on('remove', () => {
        if (!host) return;
        ko.cleanNode(host);
        host = null;
        restoreFocus(opener);
        opener = null;
    });

    layer.bindPopup(popup);
}

/** Test seam: empty the page cache between cases. */
export function _resetCacheForTests() {
    cache.clear();
}

/** Test seam: how many entries the page cache holds. */
export function _cacheSize() {
    return cache.size;
}
