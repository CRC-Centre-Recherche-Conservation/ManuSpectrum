/**
 * Vitest golden spec — the reader's `referenceNormalize` against the fixture
 * the Python twin is tested on.
 *
 * `manuspectrum/utils/xy_transforms.py` reimplements this arithmetic so the
 * spectrum preview can decimate server-side without sending a 2.8 MB file to a
 * popup. Both sides read `tests/fixtures/xy/fors_reference.csv` and assert the
 * numbers in `fors_reference.expected.json`, which is what keeps them from
 * drifting apart.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

import { describe, expect, it } from 'vitest';

import { referenceNormalize } from './xy-transforms.js';

const FIXTURES = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    '../../../../tests/fixtures/xy'
);

/** The fixture as parsed columns: [wavelength, target, reference]. */
const columns = () => {
    const rows = fs
        .readFileSync(path.join(FIXTURES, 'fors_reference.csv'), 'utf-8')
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .slice(1)
        .map((line) => line.split(',').map(Number));
    return [0, 1, 2].map((index) => rows.map((row) => row[index]));
};

const expected = () =>
    JSON.parse(
        fs.readFileSync(path.join(FIXTURES, 'fors_reference.expected.json'), 'utf-8')
    );

describe('utils/xy-transforms — golden fixture shared with the Python twin', () => {
    it('normalises the FORS fixture to the recorded curve', () => {
        const [xs, target, reference] = columns();
        const roles = ['x', 'yLeft', 'reference'];

        const result = referenceNormalize([xs, target, reference], roles);
        const values = result.series[result.roles.indexOf('yLeft')];
        const drawn = xs
            .map((x, index) => [x, values[index]])
            .filter((point) => Number.isFinite(point[1]));

        const golden = expected();
        expect(drawn.map((point) => point[0])).toEqual(golden.x);
        expect(drawn).toHaveLength(golden.y.length);
        drawn.forEach((point, index) => {
            expect(point[1]).toBeCloseTo(golden.y[index], 10);
        });
    });

    it('drops the row whose reference is zero', () => {
        const [xs, target, reference] = columns();

        const result = referenceNormalize(
            [xs, target, reference],
            ['x', 'yLeft', 'reference']
        );
        const values = result.series[result.roles.indexOf('yLeft')];
        const dropped = xs.filter((x, index) => !Number.isFinite(values[index]));

        expect(dropped).toEqual([352]);
    });
});
