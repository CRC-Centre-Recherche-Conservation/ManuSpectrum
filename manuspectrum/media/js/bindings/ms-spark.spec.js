/**
 * Vitest unit spec — bindings/ms-spark.js.
 *
 * The binding draws a series the server built from a file a curator uploaded,
 * so the SVG is assembled node by node and nothing from the payload is ever
 * parsed as markup. The rest covers the degenerate series that draw nothing,
 * and the teardown: a popup is destroyed and rebuilt on every click, so an
 * in-flight request must not outlive its element.
 *
 * Note: this file lives under media/js/bindings/, which coverage.include does
 * not target, so it executes without touching the coverage gate.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';

import './ms-spark.js';

const FILE_ID = '3f2b1c44-2c0e-4f2e-9f3a-9a1d0c5e7b21';

/** One turn of the microtask queue plus one timer, so a fetch chain settles. */
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

const served = (status, payload) =>
    vi.fn(() =>
        Promise.resolve({
            status,
            json: () => Promise.resolve(payload),
        })
    );

const mount = (spark) => {
    const root = document.createElement('div');
    root.innerHTML = '<a class="ms-summary-spark" data-bind="msSpark: spark"></a>';
    document.body.appendChild(root);
    ko.applyBindings({ spark }, root);
    return root;
};

const anchor = (root) => root.querySelector('.ms-summary-spark');

/** The `points` attribute of the drawn polyline, as pairs of numbers. */
const pairs = (root) =>
    (anchor(root).querySelector('polyline').getAttribute('points') || '')
        .split(' ')
        .filter(Boolean)
        .map((pair) => pair.split(',').map(Number));

describe('bindings/ms-spark', () => {
    beforeEach(() => {
        vi.stubGlobal('fetch', served(204, null));
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        document.body.innerHTML = '';
    });

    it('asks the language-neutral preview route for the file of the popup', async () => {
        const root = mount({ fileId: FILE_ID, title: 'FORS' });
        await flush();

        expect(fetch).toHaveBeenCalledTimes(1);
        const [url, options] = fetch.mock.calls[0];
        expect(url).toBe(`/api/spectrum-preview/${FILE_ID}`);
        expect(options.credentials).toBe('same-origin');
        expect(options.signal).toBeInstanceOf(AbortSignal);
        expect(root).toBeTruthy();
    });

    it('draws the served points as one polyline', async () => {
        vi.stubGlobal(
            'fetch',
            served(200, { x: [0, 1, 2], y: [0, 5, 10], n_source: 3, decimated: false })
        );
        const root = mount({ fileId: FILE_ID, title: 'FORS' });
        await flush();

        const svg = anchor(root).querySelector('svg');
        expect(svg.getAttribute('viewBox')).toBe('0 0 100 32');
        expect(svg.getAttribute('preserveAspectRatio')).toBe('none');
        expect(svg.getAttribute('role')).toBe('img');
        expect(svg.querySelector('title').textContent).toBe('FORS');
        const polyline = svg.querySelector('polyline');
        expect(polyline.getAttribute('fill')).toBe('none');
        expect(polyline.getAttribute('stroke')).toBe('currentColor');
        expect(polyline.getAttribute('vector-effect')).toBe('non-scaling-stroke');
        expect(pairs(root)).toEqual([
            [0, 32],
            [50, 16],
            [100, 0],
        ]);
    });

    it('builds the drawing as nodes, never as markup', async () => {
        vi.stubGlobal('fetch', served(200, { x: [0, 1], y: [0, 1] }));
        const root = mount({ fileId: FILE_ID, title: '<img onerror=alert(1)>' });
        const written = [];
        Object.defineProperty(anchor(root), 'innerHTML', {
            configurable: true,
            get: () => '',
            set: (value) => {
                written.push(value);
            },
        });
        await flush();

        expect(written).toEqual([]);
        expect(anchor(root).querySelector('title').textContent).toBe(
            '<img onerror=alert(1)>'
        );
        expect(anchor(root).querySelector('img')).toBeNull();
    });

    it('mirrors the axis when the reader draws x reversed', async () => {
        vi.stubGlobal(
            'fetch',
            served(200, { x: [0, 1, 2], y: [0, 5, 10], x_reversed: true })
        );
        const root = mount({ fileId: FILE_ID, title: '' });
        await flush();

        expect(pairs(root)).toEqual([
            [100, 32],
            [50, 16],
            [0, 0],
        ]);
    });

    it('draws a flat series along the middle of the box', async () => {
        vi.stubGlobal('fetch', served(200, { x: [0, 1, 2], y: [7, 7, 7] }));
        const root = mount({ fileId: FILE_ID, title: '' });
        await flush();

        expect(pairs(root)).toEqual([
            [0, 16],
            [50, 16],
            [100, 16],
        ]);
    });

    it('skips the points that are not finite', async () => {
        vi.stubGlobal(
            'fetch',
            served(200, { x: [0, 1, 2, null], y: [0, 'nope', 10, 4] })
        );
        const root = mount({ fileId: FILE_ID, title: '' });
        await flush();

        expect(pairs(root)).toEqual([
            [0, 32],
            [100, 0],
        ]);
    });

    it('hides the block when the file has no preview', async () => {
        const root = mount({ fileId: FILE_ID, title: '' });
        await flush();

        expect(anchor(root).hidden).toBe(true);
        expect(anchor(root).querySelector('svg')).toBeNull();
    });

    it('hides the block when fewer than two points came back', async () => {
        vi.stubGlobal('fetch', served(200, { x: [1], y: [2] }));
        const root = mount({ fileId: FILE_ID, title: '' });
        await flush();

        expect(anchor(root).hidden).toBe(true);
    });

    it('hides the block when every point shares one x', async () => {
        vi.stubGlobal('fetch', served(200, { x: [3, 3, 3], y: [1, 2, 3] }));
        const root = mount({ fileId: FILE_ID, title: '' });
        await flush();

        expect(anchor(root).hidden).toBe(true);
    });

    it('hides the block when the request fails', async () => {
        vi.stubGlobal(
            'fetch',
            vi.fn(() => Promise.reject(new Error('offline')))
        );
        const root = mount({ fileId: FILE_ID, title: '' });
        await flush();

        expect(anchor(root).hidden).toBe(true);
    });

    it('hides the block when no file was handed over', async () => {
        const root = mount(null);
        await flush();

        expect(fetch).not.toHaveBeenCalled();
        expect(anchor(root).hidden).toBe(true);
    });

    it('aborts the request when Knockout disposes the node', async () => {
        const root = mount({ fileId: FILE_ID, title: '' });
        const { signal } = fetch.mock.calls[0][1];

        ko.removeNode(root);

        expect(signal.aborted).toBe(true);
    });

    it('draws nothing into an element that was disposed mid-flight', async () => {
        let settle;
        vi.stubGlobal(
            'fetch',
            vi.fn(() => new Promise((resolve) => (settle = resolve)))
        );
        const root = mount({ fileId: FILE_ID, title: '' });
        const element = anchor(root);

        ko.removeNode(root);
        settle({ status: 200, json: () => Promise.resolve({ x: [0, 1], y: [0, 1] }) });
        await flush();

        expect(element.querySelector('svg')).toBeNull();
    });

    it('subscribes to nothing it is handed', async () => {
        const spark = ko.observable({ fileId: FILE_ID, title: '' });
        mount(spark);
        await flush();

        expect(spark.getSubscriptionsCount()).toBe(0);
    });
});
