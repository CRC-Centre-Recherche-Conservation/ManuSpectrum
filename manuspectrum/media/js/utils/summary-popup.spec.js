/**
 * Vitest unit spec — utils/summary-popup.js.
 *
 * Covers the three things the module owns: the refcounted page cache (one
 * request per resource, abort only when the last reader leaves a pending
 * request, resolved entries kept under a cap), the batch warm-up, and the two
 * popup binders (Mapbox cleanup, Leaflet host lifecycle).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';

vi.mock('arches', () => ({
    default: { urls: { root: '/fr/' }, translations: { summaryClose: 'Fermer' } },
}));

const { leafletPopups } = vi.hoisted(() => ({ leafletPopups: [] }));

vi.mock('leaflet', () => ({
    default: {
        popup: (options) => {
            const handlers = {};
            const instance = {
                options,
                content: null,
                remove: vi.fn(),
                on(name, handler) {
                    (handlers[name] = handlers[name] || []).push(handler);
                    return instance;
                },
                setContent(node) {
                    instance.content = node;
                    return instance;
                },
                emit(name) {
                    (handlers[name] || []).forEach((handler) => handler());
                },
            };
            leafletPopups.push(instance);
            return instance;
        },
    },
}));

import {
    _cacheSize,
    _resetCacheForTests,
    acquireSummary,
    attachMapboxPopupCleanup,
    bindLeafletSummaryPopup,
    summaryUrl,
    warmSummaryCache,
} from './summary-popup.js';

const ID = '11111111-1111-4111-8111-111111111111';
const OTHER = '22222222-2222-4222-8222-222222222222';
const THIRD = '33333333-3333-4333-8333-333333333333';

const uuidAt = (index) => `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`;

const response = (body, status = 200) => ({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
});

const abortError = () => {
    const error = new Error('aborted');
    error.name = 'AbortError';
    return error;
};

const flush = () => new Promise((resolve) => { setTimeout(resolve, 0); });

const raceSettle = (promise) => Promise.race([
    promise.then(() => 'settled', () => 'rejected'),
    new Promise((resolve) => { setTimeout(() => resolve('pending'), 5); }),
]);

let fetchMock;

beforeEach(() => {
    _resetCacheForTests();
    leafletPopups.length = 0;
    document.documentElement.lang = '';
    fetchMock = vi.fn(() => Promise.resolve(response({ resourceid: ID })));
    vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
    _resetCacheForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    document.documentElement.lang = '';
    document.body.innerHTML = '';
});

describe('summaryUrl', () => {
    it('hangs the id off the Arches root, which already carries the language', () => {
        expect(summaryUrl(ID)).toBe(`/fr/api/summary/${ID}`);
    });
});

describe('acquireSummary', () => {
    it('issues one request for two readers of the same resource', async () => {
        const first = acquireSummary(ID);
        const second = acquireSummary(ID);

        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(await second.promise).toBe(await first.promise);
        expect(await first.promise).toEqual({ status: 'ok', data: { resourceid: ID } });
    });

    it('sends same-origin credentials and asks for JSON', () => {
        acquireSummary(ID);

        expect(fetchMock).toHaveBeenCalledWith(
            `/fr/api/summary/${ID}`,
            expect.objectContaining({
                credentials: 'same-origin',
                headers: { Accept: 'application/json' },
            }),
        );
    });

    it('keys the entry by language, so a language switch refetches', () => {
        document.documentElement.lang = 'en';
        acquireSummary(ID);
        document.documentElement.lang = 'fr';
        acquireSummary(ID);

        expect(fetchMock).toHaveBeenCalledTimes(2);
        expect(_cacheSize()).toBe(2);
    });

    describe('refcount', () => {
        let signal;

        beforeEach(() => {
            fetchMock.mockImplementation((url, init) => {
                signal = init.signal;
                return new Promise((_resolve, reject) => {
                    init.signal.addEventListener('abort', () => reject(abortError()));
                });
            });
        });

        it('aborts and drops the entry when the last reader leaves a pending request', async () => {
            const handle = acquireSummary(ID);

            handle.release();

            expect(signal.aborted).toBe(true);
            expect(_cacheSize()).toBe(0);
            expect(await raceSettle(handle.promise)).toBe('pending');
        });

        it('keeps the request alive while another reader holds it', () => {
            const first = acquireSummary(ID);
            const second = acquireSummary(ID);

            first.release();

            expect(signal.aborted).toBe(false);
            expect(_cacheSize()).toBe(1);

            second.release();

            expect(signal.aborted).toBe(true);
            expect(_cacheSize()).toBe(0);
        });

        it('counts a reader that releases twice only once', () => {
            const first = acquireSummary(ID);
            acquireSummary(ID);

            first.release();
            first.release();

            expect(signal.aborted).toBe(false);
            expect(_cacheSize()).toBe(1);
        });
    });

    it('keeps a resolved entry when its last reader leaves', async () => {
        const first = acquireSummary(ID);
        await first.promise;

        first.release();

        expect(_cacheSize()).toBe(1);
        const second = acquireSummary(ID);
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(await second.promise).toEqual({ status: 'ok', data: { resourceid: ID } });
    });

    it('reports 403 as forbidden', async () => {
        fetchMock.mockResolvedValue(response({ error: 'forbidden' }, 403));

        expect(await acquireSummary(ID).promise).toEqual({ status: 'forbidden' });
    });

    it('reports 404 as notfound', async () => {
        fetchMock.mockResolvedValue(response({ error: 'not_found' }, 404));

        expect(await acquireSummary(ID).promise).toEqual({ status: 'notfound' });
    });

    it('reports any other refusal as network', async () => {
        fetchMock.mockResolvedValue(response({ error: 'unavailable' }, 503));

        expect(await acquireSummary(ID).promise).toEqual({ status: 'network' });
    });

    it('reports a failed request as network', async () => {
        fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

        expect(await acquireSummary(ID).promise).toEqual({ status: 'network' });
    });

    it('reports an unreadable body as network', async () => {
        fetchMock.mockResolvedValue({
            ok: true,
            status: 200,
            json: () => Promise.reject(new SyntaxError('Unexpected token')),
        });

        expect(await acquireSummary(ID).promise).toEqual({ status: 'network' });
    });

    it('never settles when the body read is aborted', async () => {
        fetchMock.mockResolvedValue({
            ok: true,
            status: 200,
            json: () => Promise.reject(abortError()),
        });

        expect(await raceSettle(acquireSummary(ID).promise)).toBe('pending');
    });

    it('caps resolved entries at 50, dropping the oldest', async () => {
        for (let index = 0; index < 51; index += 1) {
            const handle = acquireSummary(uuidAt(index));
            await handle.promise;
            handle.release();
        }

        expect(_cacheSize()).toBe(50);

        fetchMock.mockClear();
        acquireSummary(uuidAt(0));
        expect(fetchMock).toHaveBeenCalledTimes(1);

        fetchMock.mockClear();
        acquireSummary(uuidAt(50));
        expect(fetchMock).not.toHaveBeenCalled();
    });
});

describe('warmSummaryCache', () => {
    it('fills the missing entries from one batch request', async () => {
        fetchMock.mockResolvedValue(response({
            summaries: { [ID]: { resourceid: ID }, [OTHER]: { resourceid: OTHER } },
        }));

        warmSummaryCache([ID, OTHER, THIRD]);
        await flush();

        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(fetchMock.mock.calls[0][0]).toBe(
            `/fr/api/summary?ids=${ID},${OTHER},${THIRD}`,
        );
        expect(_cacheSize()).toBe(2);

        const handle = acquireSummary(ID);
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(await handle.promise).toEqual({ status: 'ok', data: { resourceid: ID } });
    });

    it('does nothing for fewer than two ids', () => {
        warmSummaryCache([ID]);

        expect(fetchMock).not.toHaveBeenCalled();
        expect(_cacheSize()).toBe(0);
    });

    it('does nothing for more than ten ids', () => {
        warmSummaryCache(Array.from({ length: 11 }, (_unused, index) => uuidAt(index)));

        expect(fetchMock).not.toHaveBeenCalled();
        expect(_cacheSize()).toBe(0);
    });

    it('does nothing when handed something that is not a list', () => {
        warmSummaryCache(undefined);

        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('never overwrites an entry the page already holds', async () => {
        const held = acquireSummary(ID);
        await held.promise;
        fetchMock.mockResolvedValue(response({
            summaries: { [ID]: { resourceid: 'stale' }, [OTHER]: { resourceid: OTHER } },
        }));

        warmSummaryCache([ID, OTHER]);
        await flush();

        expect(await acquireSummary(ID).promise).toEqual({
            status: 'ok',
            data: { resourceid: ID },
        });
    });

    it('skips the request when every id is already held', async () => {
        const first = acquireSummary(ID);
        const second = acquireSummary(OTHER);
        await Promise.all([first.promise, second.promise]);
        fetchMock.mockClear();

        warmSummaryCache([ID, OTHER]);
        await flush();

        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('ignores a refused warm-up', async () => {
        fetchMock.mockResolvedValue(response({ error: 'too_many_ids' }, 400));

        warmSummaryCache([ID, OTHER]);
        await flush();

        expect(_cacheSize()).toBe(0);
    });

    it('ignores a failed warm-up', async () => {
        fetchMock.mockRejectedValue(new TypeError('Failed to fetch'));

        expect(() => warmSummaryCache([ID, OTHER])).not.toThrow();
        await flush();

        expect(_cacheSize()).toBe(0);
    });
});

describe('attachMapboxPopupCleanup', () => {
    const build = () => {
        const content = document.createElement('div');
        content.innerHTML = '<button class="mapboxgl-popup-close-button"></button>';
        document.body.appendChild(content);
        const handlers = {};
        const popup = {
            _content: content,
            remove: vi.fn(),
            on: vi.fn((name, handler) => { handlers[name] = handler; }),
        };
        return { content, handlers, popup, data: { popupFeatures: [{ mapCard: { popup } }] } };
    };

    it('returns the data it was handed', () => {
        const { data } = build();

        expect(attachMapboxPopupCleanup(data)).toBe(data);
    });

    it('translates the close button label', () => {
        const { content, data } = build();

        attachMapboxPopupCleanup(data);

        expect(
            content.querySelector('.mapboxgl-popup-close-button').getAttribute('aria-label'),
        ).toBe('Fermer');
    });

    it('closes the popup on Escape', () => {
        const { content, data, popup } = build();

        attachMapboxPopupCleanup(data);
        content.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));

        expect(popup.remove).toHaveBeenCalledTimes(1);
    });

    it('cleans the node and drops the Escape listener on close', () => {
        const { content, data, handlers, popup } = build();
        const cleanNode = vi.spyOn(ko, 'cleanNode');

        attachMapboxPopupCleanup(data);
        handlers.close();

        expect(cleanNode).toHaveBeenCalledWith(content);
        content.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(popup.remove).not.toHaveBeenCalled();
    });

    it('attaches once per popup', () => {
        const { data, popup } = build();

        attachMapboxPopupCleanup(data);
        attachMapboxPopupCleanup(data);

        expect(popup.on).toHaveBeenCalledTimes(1);
    });

    it('closes the popup on the legacy Esc key name', () => {
        const { content, data, popup } = build();

        attachMapboxPopupCleanup(data);
        content.dispatchEvent(new KeyboardEvent('keydown', { key: 'Esc' }));

        expect(popup.remove).toHaveBeenCalledTimes(1);
    });

    it('leaves another key alone', () => {
        const { content, data, popup } = build();

        attachMapboxPopupCleanup(data);
        content.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }));

        expect(popup.remove).not.toHaveBeenCalled();
    });

    it('binds a popup whose close button is not in the markup', () => {
        const { content, data, popup } = build();
        content.innerHTML = '';

        expect(() => attachMapboxPopupCleanup(data)).not.toThrow();
        expect(popup.on).toHaveBeenCalledTimes(1);
    });

    it('tolerates data with no popup, and a popup with no content', () => {
        const orphan = { on: vi.fn() };

        expect(attachMapboxPopupCleanup(undefined)).toBeUndefined();
        expect(() => attachMapboxPopupCleanup({ popupFeatures: [] })).not.toThrow();
        expect(() => attachMapboxPopupCleanup({ popupFeatures: [{ mapCard: {} }] })).not.toThrow();
        attachMapboxPopupCleanup({ popupFeatures: [{ mapCard: { popup: orphan } }] });
        expect(orphan.on).not.toHaveBeenCalled();
    });
});

describe('bindLeafletSummaryPopup', () => {
    const feature = {
        properties: {
            resourceId: ID,
            graphName: 'Document',
            tileId: 'tile-1',
            nodeId: 'node-1',
            canvas: 'canvas-1',
        },
    };

    it('ignores a feature that names no resource', () => {
        const layer = { bindPopup: vi.fn() };

        bindLeafletSummaryPopup({ properties: {} }, layer);

        expect(leafletPopups).toHaveLength(0);
        expect(layer.bindPopup).not.toHaveBeenCalled();
    });

    it('ignores a missing feature', () => {
        const layer = { bindPopup: vi.fn() };

        expect(() => bindLeafletSummaryPopup(undefined, layer)).not.toThrow();
        expect(layer.bindPopup).not.toHaveBeenCalled();
    });

    it('binds a sized popup to the layer', () => {
        const layer = { bindPopup: vi.fn() };

        bindLeafletSummaryPopup(feature, layer);

        expect(leafletPopups).toHaveLength(1);
        expect(leafletPopups[0].options).toEqual({
            maxWidth: 360,
            minWidth: 260,
            className: 'ms-summary-popup-shell',
        });
        expect(layer.bindPopup).toHaveBeenCalledWith(leafletPopups[0]);
    });

    it('mounts the component on a focusable host when the popup opens', () => {
        const applyBindingsToNode = vi
            .spyOn(ko, 'applyBindingsToNode')
            .mockImplementation(() => {});
        bindLeafletSummaryPopup(feature, { bindPopup: vi.fn() });
        const popup = leafletPopups[0];

        popup.emit('add');

        expect(popup.content.tagName).toBe('DIV');
        expect(popup.content.tabIndex).toBe(-1);
        expect(applyBindingsToNode).toHaveBeenCalledWith(popup.content, {
            component: {
                name: 'ms-summary-popup',
                params: {
                    resourceId: ID,
                    graphName: 'Document',
                    surface: 'iiif',
                    context: { tileId: 'tile-1', nodeId: 'node-1', canvas: 'canvas-1' },
                },
            },
        });
    });

    it('cleans the host when the popup closes, once', () => {
        vi.spyOn(ko, 'applyBindingsToNode').mockImplementation(() => {});
        const cleanNode = vi.spyOn(ko, 'cleanNode');
        bindLeafletSummaryPopup(feature, { bindPopup: vi.fn() });
        const popup = leafletPopups[0];

        popup.emit('add');
        const host = popup.content;
        popup.emit('remove');
        popup.emit('remove');

        expect(cleanNode).toHaveBeenCalledTimes(1);
        expect(cleanNode).toHaveBeenCalledWith(host);
    });

    it('builds a fresh host on every open', () => {
        vi.spyOn(ko, 'applyBindingsToNode').mockImplementation(() => {});
        bindLeafletSummaryPopup(feature, { bindPopup: vi.fn() });
        const popup = leafletPopups[0];

        popup.emit('add');
        const first = popup.content;
        popup.emit('remove');
        popup.emit('add');

        expect(popup.content).not.toBe(first);
    });
});
