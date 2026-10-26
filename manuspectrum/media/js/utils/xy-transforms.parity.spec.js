/**
 * Vitest parity spec — the XY reader's drawing of every renderer configuration
 * in use, against the series the server draws.
 *
 * `tests/fixtures/xy/parity/cases.json` holds, per configuration, a copy of the
 * stored configuration and the series `read_series` draws from an excerpt of a
 * real file of its technique; `tests/test_spectrum_preview.py`
 * (`ConfigurationParityTests`) pins the server side. Here the file goes through
 * the reader's own pipeline: the parser, then the configuration's corrective
 * chain, then the first left-axis series, as `xy-reader.js` plots it.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

import { describe, expect, it } from 'vitest';

import XyParser from './xy-parser';
import { applyTransforms, expandStoredConfig, seriesRoles } from './xy-transforms.js';

const PARITY = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    '../../../../tests/fixtures/xy/parity'
);

const cases = JSON.parse(fs.readFileSync(path.join(PARITY, 'cases.json'), 'utf-8'));

/** The curve the reader draws on its left axis, finite points only. */
const drawn = (text, stored) => {
    const config = expandStoredConfig(stored);
    const parsed = applyTransforms(XyParser.parse(text, config), config);
    let values = parsed.y;
    if (parsed.ys) {
        const roles = seriesRoles(parsed, config);
        const index = parsed.ys.findIndex(
            (_, i) => (roles[i] || 'yLeft') !== 'yRight' && roles[i] !== 'ignore'
        );
        values = parsed.ys[index];
    }
    const points = parsed.x
        .map((x, i) => [x, values[i]])
        .filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
    return {
        x: points.map((point) => point[0]),
        y: points.map((point) => point[1]),
        xReversed: Boolean(config?.display?.xReversed),
    };
};

describe('utils/xy-transforms — parity with the server for every configuration in use', () => {
    it('covers the five configurations in use', () => {
        expect(cases.map((c) => c.configId.slice(-4)).sort()).toEqual([
            '6a01',
            '6a03',
            '6a04',
            '6a06',
            '6a0c',
        ]);
    });

    it.each(cases.map((c) => [c.name, c]))('draws %s as the server does', (_, c) => {
        const text = fs.readFileSync(path.join(PARITY, c.file), 'utf-8');

        const curve = drawn(text, c.config);

        expect(curve.x).toEqual(c.expected.x);
        expect(curve.y).toHaveLength(c.expected.y.length);
        curve.y.forEach((y, i) => {
            expect(y).toBeCloseTo(c.expected.y[i], 12);
        });
        expect(curve.xReversed).toBe(c.expected.x_reversed);
    });
});
