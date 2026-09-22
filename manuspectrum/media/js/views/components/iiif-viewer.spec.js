/**
 * Vitest unit spec — iiif-viewer.js (project wrapper over the core viewer).
 *
 * The wrapper carries one rule and one side effect: every host that does not
 * pass `onEachFeature` gets the summary-popup binder on the read-only
 * annotation layer, and the 'iiif-viewer' Knockout component is re-registered
 * so the hosts that resolve it by name reach the wrapper too. The core
 * viewmodel is mocked: it is applied to `this`, which the third test pins.
 *
 * Note: this file lives under media/js/views/components/, which coverage.include
 * does not target, so it executes without touching the coverage gate.
 */

import { beforeAll, describe, expect, it, vi } from 'vitest';
import ko from 'knockout';
import L from 'leaflet';

vi.mock('arches/arches/app/media/js/views/components/iiif-viewer', () => ({
    default: vi.fn(function (params) {
        this.received = params;
    }),
}));

vi.mock('utils/summary-popup', () => ({
    bindLeafletSummaryPopup: vi.fn(),
}));

vi.mock('views/components/ms-summary-popup', () => ({}));

import CoreIIIFViewerViewmodel from 'arches/arches/app/media/js/views/components/iiif-viewer';
import { bindLeafletSummaryPopup } from 'utils/summary-popup';

let IIIFViewerViewmodel;
let stackSmallestOnTop;
let registration;
let unregistered;

beforeAll(async () => {
    const unregisterSpy = vi
        .spyOn(ko.components, 'unregister')
        .mockImplementation((name) => {
            unregistered = name;
        });
    const registerSpy = vi
        .spyOn(ko.components, 'register')
        .mockImplementation((name, config) => {
            registration = { name, config };
        });
    const module = await import('./iiif-viewer.js');
    registerSpy.mockRestore();
    unregisterSpy.mockRestore();
    IIIFViewerViewmodel = module.default;
    stackSmallestOnTop = module.stackSmallestOnTop;
});

function fakeMap(layers) {
    const handlers = {};
    return {
        layers,
        on: (event, handler) => {
            handlers[event] = handler;
        },
        emit: (event, payload) => handlers[event](payload),
        eachLayer: (fn) => layers.forEach(fn),
    };
}

function annotation(layer) {
    layer.feature = { type: 'Feature', properties: {} };
    layer.bringToFront = vi.fn();
    return layer;
}

describe('iiif-viewer wrapper', () => {
    it('hands the summary popup binder to the core viewmodel', () => {
        const params = { manifest: 'm' };
        const viewModel = new IIIFViewerViewmodel(params);

        expect(viewModel.received.onEachFeature).toBe(bindLeafletSummaryPopup);
        expect(viewModel.received.manifest).toBe('m');
        expect(params.onEachFeature).toBeUndefined();
        expect(CoreIIIFViewerViewmodel).toHaveBeenCalled();
    });

    it("keeps the host's own onEachFeature", () => {
        const onEachFeature = vi.fn();
        const viewModel = new IIIFViewerViewmodel({ onEachFeature });

        expect(viewModel.received.onEachFeature).toBe(onEachFeature);
        expect(viewModel.received.onEachFeature).not.toBe(bindLeafletSummaryPopup);
    });

    it('applies the core viewmodel to its own instance', () => {
        const viewModel = new IIIFViewerViewmodel({});

        expect(CoreIIIFViewerViewmodel.mock.instances.at(-1)).toBe(viewModel);
    });

    it('re-registers the iiif-viewer component on the wrapper', () => {
        expect(unregistered).toBe('iiif-viewer');
        expect(registration.name).toBe('iiif-viewer');
        expect(registration.config.viewModel).toBe(IIIFViewerViewmodel);
    });

    it('restacks annotations largest first once a batch is drawn', () => {
        const large = annotation(L.polygon([[0, 0], [0, 10], [10, 10], [10, 0]]));
        const small = annotation(L.polygon([[1, 1], [1, 2], [2, 2], [2, 1]]));
        const point = annotation(L.circleMarker([5, 5]));
        const scheduled = [];
        const map = fakeMap([small, point, large]);

        stackSmallestOnTop(map, (fn) => scheduled.push(fn));
        map.emit('layeradd', { layer: small });
        map.emit('layeradd', { layer: large });
        map.emit('layeradd', { layer: { feature: {} } });

        expect(scheduled).toHaveLength(1);
        scheduled[0]();
        const order = [large, small, point].map((l) => l.bringToFront.mock.invocationCallOrder[0]);
        expect(order[0]).toBeLessThan(order[1]);
        expect(order[1]).toBeLessThan(order[2]);

        map.emit('layeradd', { layer: small });
        expect(scheduled).toHaveLength(2);
    });

    it('keeps the pinned paths above the restacked annotations', () => {
        const large = annotation(L.polygon([[0, 0], [0, 10], [10, 10], [10, 0]]));
        const small = annotation(L.polygon([[1, 1], [1, 2], [2, 2], [2, 1]]));
        const drawn = annotation(L.polygon([[0, 0], [0, 20], [20, 20], [20, 0]]));
        const scheduled = [];
        const map = fakeMap([drawn, small, large]);

        stackSmallestOnTop(map, (fn) => scheduled.push(fn), (layer) => layer === drawn);
        map.emit('layeradd', { layer: drawn });
        scheduled[0]();

        const order = [large, small, drawn].map((l) => l.bringToFront.mock.invocationCallOrder[0]);
        expect(order[0]).toBeLessThan(order[1]);
        expect(order[1]).toBeLessThan(order[2]);
    });

    it("pins the shapes of the host's own drawLayer", () => {
        const drawn = annotation(L.polygon([[0, 0], [0, 20], [20, 20], [20, 0]]));
        const small = annotation(L.polygon([[1, 1], [1, 2], [2, 2], [2, 1]]));
        const map = fakeMap([drawn, small]);
        CoreIIIFViewerViewmodel.mockImplementationOnce(function () {
            this.map = ko.observable(map);
            this.drawLayer = ko.observable({ hasLayer: (layer) => layer === drawn });
        });
        vi.useFakeTimers();
        try {
            new IIIFViewerViewmodel({});
            map.emit('layeradd', { layer: small });
            vi.runAllTimers();
        } finally {
            vi.useRealTimers();
        }

        const order = [small, drawn].map((l) => l.bringToFront.mock.invocationCallOrder[0]);
        expect(order[0]).toBeLessThan(order[1]);
    });

    it('hooks the restacking on the map the core viewmodel creates', () => {
        const map = fakeMap([]);
        const onSpy = vi.spyOn(map, 'on');
        CoreIIIFViewerViewmodel.mockImplementationOnce(function () {
            this.map = ko.observable();
        });
        const viewModel = new IIIFViewerViewmodel({});
        expect(onSpy).not.toHaveBeenCalled();

        viewModel.map(map);
        expect(onSpy).toHaveBeenCalledWith('layeradd', expect.any(Function));

        viewModel.map(fakeMap([]));
        expect(onSpy).toHaveBeenCalledTimes(1);
    });
});
