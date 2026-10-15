/**
 * Vitest unit spec — utils/iiif-annotation-nodes.js.
 *
 * The builder replaces the core viewer's per-canvas preload: one counts
 * request per node, the current canvas still loaded through `iiifannotations`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';

vi.mock('arches', () => ({
    default: { urls: { iiifannotations: '/en/iiifannotations' } },
}));

vi.mock('@/arches/utils/generate-arches-url.ts', () => ({
    generateArchesURL: vi.fn((name) => {
        if (name !== 'manuspectrum:api-iiif-annotation-counts') throw new Error(name);
        return '/api/iiif-annotation-counts';
    }),
}));

import { createBuildAnnotationNodes } from './iiif-annotation-nodes';

const NODE_A = { nodeid: 'aaaa', name: 'Zones', graph_name: 'Analysis', icon: 'fa fa-a' };
const NODE_B = { nodeid: 'bbbb', name: 'Zones', graph_name: 'Component', icon: 'fa fa-b' };

function viewer(canvas = 'c1') {
    return {
        canvas: ko.observable(canvas),
        manifestData: ko.observable(),
        annotationNodes: ko.observableArray(),
        annotationCounts: ko.observable({}),
    };
}

function respond(body, ok = true) {
    return { ok, status: ok ? 200 : 500, json: async () => body };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

let routes;
let fetchMock;

beforeEach(() => {
    routes = {
        '/en/iiifannotations?canvas=c1&nodeid=aaaa': {
            features: [{ properties: {} }, { properties: {} }],
        },
        '/en/iiifannotations?canvas=c2&nodeid=aaaa': { features: [{ properties: {} }] },
        '/en/iiifannotations?canvas=c1&nodeid=bbbb': { features: [{ properties: {} }] },
        '/en/iiifannotations?canvas=c3&nodeid=aaaa': { features: [] },
        '/en/iiifannotations?canvas=c3&nodeid=bbbb': { features: [] },
        '/en/iiifannotations?canvas=c2&nodeid=bbbb': { features: [] },
        '/api/iiif-annotation-counts?nodeid=aaaa': { c1: 2, c2: 1, c3: 4 },
        '/api/iiif-annotation-counts?nodeid=bbbb': { c1: 1 },
    };
    fetchMock = vi.fn(async (url) => respond(routes[url]));
    vi.stubGlobal('fetch', fetchMock);
    window.fetch = fetchMock;
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

const countsCalls = () => fetchMock.mock.calls.filter(([url]) => url.includes('iiif-annotation-counts'));

describe('createBuildAnnotationNodes', () => {
    it('builds one node per annotation node, shaped as the core does', () => {
        const v = viewer();
        createBuildAnnotationNodes(v)([NODE_A]);

        const [node] = v.annotationNodes();
        expect(node.name).toBe('Analysis - Zones');
        expect(node.icon).toBe('fa fa-a');
        expect(node.active()).toBe(false);
        expect(node.opacity()).toBe(100);
    });

    it('asks the counts of a node once, whatever the number of canvases', async () => {
        const v = viewer();
        createBuildAnnotationNodes(v)([NODE_A, NODE_B]);
        await flush();
        v.canvas('c2');
        v.manifestData({ sequences: [] });
        v.canvas('c3');
        await flush();

        expect(countsCalls().map(([url]) => url)).toEqual([
            '/api/iiif-annotation-counts?nodeid=aaaa',
            '/api/iiif-annotation-counts?nodeid=bbbb',
        ]);
    });

    it('sums the counts of the nodes per canvas', async () => {
        const v = viewer();
        createBuildAnnotationNodes(v)([NODE_A, NODE_B]);
        await flush();

        expect(v.annotationCounts()).toEqual({ c1: 3, c2: 1, c3: 4 });
    });

    it('never requests a canvas other than the current one', async () => {
        const v = viewer();
        createBuildAnnotationNodes(v)([NODE_A]);
        await flush();

        const annotationCalls = fetchMock.mock.calls
            .map(([url]) => url)
            .filter((url) => url.startsWith('/en/iiifannotations'));
        expect(annotationCalls).toEqual(['/en/iiifannotations?canvas=c1&nodeid=aaaa']);
    });

    it('loads the annotations of the current canvas and tags them with the graph name', async () => {
        const v = viewer();
        createBuildAnnotationNodes(v)([NODE_A]);
        await flush();

        const features = v.annotationNodes()[0].annotations();
        expect(features).toHaveLength(2);
        expect(features.every((f) => f.properties.graphName === 'Analysis')).toBe(true);
    });

    it('reloads the annotations when the canvas changes, once per URL', async () => {
        const v = viewer();
        createBuildAnnotationNodes(v)([NODE_A]);
        await flush();
        v.canvas('c2');
        await flush();
        v.canvas('c1');
        await flush();

        const node = v.annotationNodes()[0];
        expect(node.annotations()).toHaveLength(2);
        const annotationCalls = fetchMock.mock.calls.filter(([url]) =>
            url.startsWith('/en/iiifannotations'),
        );
        expect(annotationCalls).toHaveLength(2);
    });

    it('does not request a canvas while none is selected', async () => {
        const v = viewer(null);
        createBuildAnnotationNodes(v)([NODE_A]);
        await flush();

        expect(
            fetchMock.mock.calls.filter(([url]) => url.startsWith('/en/iiifannotations')),
        ).toHaveLength(0);
        expect(countsCalls()).toHaveLength(1);
    });

    it('asks no counts when the host counts for itself', async () => {
        const v = viewer();
        createBuildAnnotationNodes(v, () => false)([NODE_A]);
        await flush();

        expect(countsCalls()).toHaveLength(0);
        expect(v.annotationNodes()[0].annotations()).toHaveLength(2);
    });

    it('leaves the counts empty and tries again after a failed counts request', async () => {
        const error = vi.spyOn(console, 'error').mockImplementation(() => {});
        routes['/api/iiif-annotation-counts?nodeid=aaaa'] = null;
        fetchMock.mockImplementation(async (url) =>
            url.includes('iiif-annotation-counts')
                ? respond({}, false)
                : respond(routes[url]),
        );
        const v = viewer();
        createBuildAnnotationNodes(v)([NODE_A]);
        await flush();

        expect(v.annotationCounts()).toEqual({});
        expect(error).toHaveBeenCalled();

        fetchMock.mockImplementation(async (url) => respond(routes[url] || { c1: 2 }));
        v.manifestData({ sequences: [] });
        await flush();

        expect(v.annotationCounts()).toEqual({ c1: 2 });
    });
});
