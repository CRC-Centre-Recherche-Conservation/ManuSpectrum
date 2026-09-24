/**
 * Vitest unit spec — utils/leaflet-stack.js.
 *
 * `stackSmallestOnTop` reorders the vector layers of a Leaflet map so a large
 * annotation never covers a smaller one and steals its clicks; layers a
 * caller marks as pinned stay above the restacked set.
 */

import { describe, expect, it, vi } from 'vitest';
import L from 'leaflet';

import { stackSmallestOnTop } from './leaflet-stack.js';

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

describe('leaflet-stack', () => {
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
});
