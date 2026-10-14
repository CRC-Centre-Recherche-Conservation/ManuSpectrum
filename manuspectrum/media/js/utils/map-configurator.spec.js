/**
 * Vitest unit spec — utils/map-configurator.js (shadow of the Arches core
 * project hook that `viewmodels/map.js` calls around its map `load` handler).
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { archesStub } = vi.hoisted(() => ({ archesStub: { mapboxApiKey: '' } }));

vi.mock('arches', () => ({ default: archesStub }));
vi.mock('mapbox-gl-geocoder', () => ({
    default: class MapboxGeocoder {},
}));

import MapboxGeocoder from 'mapbox-gl-geocoder';
import mapConfigurator from 'utils/map-configurator';

class FakeMap {
    constructor() {
        this.added = [];
    }
    addControl(control, position) {
        this.added.push([control, position]);
        return this;
    }
}

describe('map-configurator', () => {
    beforeEach(() => {
        archesStub.mapboxApiKey = '';
    });

    it('skips the MapboxGeocoder without a Mapbox key and keeps the other controls', () => {
        const map = new FakeMap();
        const navigation = { name: 'navigation' };
        mapConfigurator.preConfig(map);
        map.addControl(navigation, 'top-left');
        const result = map.addControl(new MapboxGeocoder(), 'top-right');
        expect(map.added).toEqual([[navigation, 'top-left']]);
        expect(result).toBe(map);
    });

    it('adds the MapboxGeocoder when a Mapbox key is set', () => {
        archesStub.mapboxApiKey = 'pk.example';
        const map = new FakeMap();
        const geocoder = new MapboxGeocoder();
        mapConfigurator.preConfig(map);
        map.addControl(geocoder, 'top-right');
        expect(map.added).toEqual([[geocoder, 'top-right']]);
    });

    it('puts the map back as it was in postConfig', () => {
        const map = new FakeMap();
        mapConfigurator.preConfig(map);
        expect(Object.prototype.hasOwnProperty.call(map, 'addControl')).toBe(true);
        mapConfigurator.postConfig(map);
        expect(Object.prototype.hasOwnProperty.call(map, 'addControl')).toBe(false);
        const geocoder = new MapboxGeocoder();
        map.addControl(geocoder, 'top-right');
        expect(map.added).toEqual([[geocoder, 'top-right']]);
    });
});
