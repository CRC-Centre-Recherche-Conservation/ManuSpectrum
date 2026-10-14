/**
 * Vitest unit spec — the vendored OpenFreeMap Positron layers
 * (constants/openfreemap_positron_layers.json) against the style specification
 * of mapbox-gl 1.13, the renderer of the Arches maps.
 */

import { describe, expect, it } from 'vitest';
import { validate } from 'mapbox-gl/dist/style-spec/index.es.js';

import layers from '../../../constants/openfreemap_positron_layers.json';

const SOURCE = { type: 'vector', url: 'https://tiles.openfreemap.org/planet' };

const styleWith = (styleLayers, sources = { openfreemap: SOURCE }) => ({
    version: 8,
    sources,
    sprite: 'https://tiles.openfreemap.org/sprites/ofm_f384/ofm',
    glyphs: 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf',
    layers: styleLayers,
});

describe('OpenFreeMap Positron layers', () => {
    it('are a valid mapbox-gl 1.13 style', () => {
        expect(validate(styleWith(layers))).toEqual([]);
    });

    it('draw only from the openfreemap source', () => {
        const sources = new Set(layers.map((layer) => layer.source).filter(Boolean));
        expect([...sources]).toEqual(['openfreemap']);
    });

    it('are rejected by the validator when a layer names an unknown source', () => {
        const broken = layers.map((layer) =>
            layer.source ? { ...layer, source: 'openmaptiles' } : layer,
        );
        const errors = validate(styleWith(broken));
        expect(errors.length).toBeGreaterThan(0);
        expect(errors[0].message).toMatch(/openmaptiles/);
    });
});
