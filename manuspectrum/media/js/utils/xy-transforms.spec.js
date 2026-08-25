import { describe, it, expect } from 'vitest';

import {
    applyTransforms,
    kubelkaMunk,
    logInverseR,
    normalizeArea,
    normalizeMax,
    referenceNormalize,
    resolveRoles,
    savitzkyGolay,
    savitzkyGolayCoefficients,
    seriesColumnIndex,
    ROLE_DARK,
    ROLE_REFERENCE,
    ROLE_Y_LEFT,
    deriveAxisLabel,
    describeChain,
} from './xy-transforms';

const closeTo = (actual, expected, precision = 10) => {
    expect(actual).toBeCloseTo(expected, precision);
};

describe('seriesColumnIndex', () => {
    it('maps series straight through in generate mode', () => {
        expect(seriesColumnIndex(0, 0, true)).toBe(0);
        expect(seriesColumnIndex(2, 0, true)).toBe(2);
    });

    it('skips over the X column otherwise', () => {
        // X is column 0, so series 0 and 1 are file columns 1 and 2.
        expect(seriesColumnIndex(0, 0, false)).toBe(1);
        expect(seriesColumnIndex(1, 0, false)).toBe(2);
    });

    it('handles an X column in the middle', () => {
        // X is column 1: series 0 -> col 0, series 1 -> col 2.
        expect(seriesColumnIndex(0, 1, false)).toBe(0);
        expect(seriesColumnIndex(1, 1, false)).toBe(2);
    });
});

describe('resolveRoles', () => {
    it('defaults every series to the left axis', () => {
        expect(resolveRoles({}, 3)).toEqual([ROLE_Y_LEFT, ROLE_Y_LEFT, ROLE_Y_LEFT]);
    });

    it('reads roles through the X-column offset', () => {
        // A FORS export: wavelength / tgt_count / ref_count.
        const config = {
            xColumnIndex: 0,
            display: {
                columnAssignments: [
                    { columnIndex: 0, role: 'x' },
                    { columnIndex: 1, role: 'yLeft' },
                    { columnIndex: 2, role: 'reference' },
                ],
            },
        };
        expect(resolveRoles(config, 2)).toEqual([ROLE_Y_LEFT, ROLE_REFERENCE]);
    });
});

describe('referenceNormalize', () => {
    it('divides the target by the white reference', () => {
        const series = [
            [10, 20, 30],
            [100, 100, 100],
        ];
        const { series: out, roles } = referenceNormalize(series, [
            ROLE_Y_LEFT,
            ROLE_REFERENCE,
        ]);

        expect(out).toHaveLength(1);
        expect(out[0]).toEqual([0.1, 0.2, 0.3]);
        // The reference column is consumed, not plotted.
        expect(roles).toEqual([ROLE_Y_LEFT]);
    });

    it('subtracts the dark current first', () => {
        // R = (S - D) / (W - D) = (30 - 10) / (110 - 10) = 0.2
        const series = [[30], [110], [10]];
        const { series: out } = referenceNormalize(series, [
            ROLE_Y_LEFT,
            ROLE_REFERENCE,
            ROLE_DARK,
        ]);
        expect(out).toHaveLength(1);
        closeTo(out[0][0], 0.2);
    });

    it('leaves the data untouched when no reference is tagged', () => {
        const series = [[1, 2, 3]];
        const { series: out } = referenceNormalize(series, [ROLE_Y_LEFT]);
        expect(out).toBe(series);
    });

    it('yields NaN rather than Infinity on a zero reference', () => {
        const { series: out } = referenceNormalize(
            [[5], [0]],
            [ROLE_Y_LEFT, ROLE_REFERENCE]
        );
        expect(Number.isNaN(out[0][0])).toBe(true);
    });

    it('keeps the original when every column is a reference', () => {
        const series = [[1, 2]];
        const { series: out } = referenceNormalize(series, [ROLE_REFERENCE]);
        expect(out).toBe(series);
    });
});

describe('pointwise transforms', () => {
    it('computes apparent absorbance log10(1/R)', () => {
        const out = logInverseR([1, 0.1, 0.01]);
        closeTo(out[0], 0);
        closeTo(out[1], 1);
        closeTo(out[2], 2);
    });

    it('returns NaN for a non-positive reflectance', () => {
        const out = logInverseR([0, -0.5]);
        expect(out.every(Number.isNaN)).toBe(true);
    });

    it('computes Kubelka-Munk remission', () => {
        // R = 0.5 -> (1 - 0.5)^2 / (2 * 0.5) = 0.25
        closeTo(kubelkaMunk([0.5])[0], 0.25);
        // A perfect reflector absorbs nothing.
        closeTo(kubelkaMunk([1])[0], 0);
    });

    it('scales the strongest point to one', () => {
        expect(normalizeMax([1, 2, 4])).toEqual([0.25, 0.5, 1]);
    });

    it('leaves an all-zero series alone rather than dividing by zero', () => {
        expect(normalizeMax([0, 0])).toEqual([0, 0]);
        expect(normalizeArea([0, 0])).toEqual([0, 0]);
    });

    it('scales the total signal to one', () => {
        const out = normalizeArea([1, 1, 2]);
        closeTo(out.reduce((a, b) => a + b, 0), 1);
    });
});

describe('savitzkyGolay', () => {
    it('reproduces the classic 5-point quadratic smoothing coefficients', () => {
        // The textbook kernel is [-3, 12, 17, 12, -3] / 35.
        const coefficients = savitzkyGolayCoefficients(5, 2, 0);
        const expected = [-3 / 35, 12 / 35, 17 / 35, 12 / 35, -3 / 35];
        coefficients.forEach((c, i) => closeTo(c, expected[i], 9));
    });

    it('leaves a polynomial of its own order untouched when smoothing', () => {
        const y = [0, 1, 4, 9, 16, 25, 36, 49, 64];
        const out = savitzkyGolay(y, { window: 5, polyOrder: 2, derivative: 0 });
        out.forEach((v, i) => closeTo(v, y[i], 6));
    });

    it('differentiates a straight line to its slope', () => {
        const y = [0, 2, 4, 6, 8, 10, 12];
        const out = savitzkyGolay(y, { window: 5, polyOrder: 2, derivative: 1 });
        out.forEach((v) => closeTo(v, 2, 6));
    });

    it('scales the derivative by the X spacing', () => {
        // Same samples, but 0.5 apart: the slope doubles.
        const y = [0, 2, 4, 6, 8, 10, 12];
        const out = savitzkyGolay(y, {
            window: 5,
            polyOrder: 2,
            derivative: 1,
            spacing: 0.5,
        });
        out.forEach((v) => closeTo(v, 4, 6));
    });

    it('finds the constant second derivative of a parabola', () => {
        const y = [0, 1, 4, 9, 16, 25, 36];
        const out = savitzkyGolay(y, { window: 5, polyOrder: 2, derivative: 2 });
        out.forEach((v) => closeTo(v, 2, 6));
    });

    it('forces the window to be odd and at least three wide', () => {
        const y = [1, 2, 3, 4, 5, 6, 7];
        expect(savitzkyGolay(y, { window: 4 })).toHaveLength(y.length);
        expect(savitzkyGolay(y, { window: 1 })).toHaveLength(y.length);
    });

    it('gives up rather than guess when the window exceeds the data', () => {
        const out = savitzkyGolay([1, 2, 3], { window: 11 });
        expect(out.every(Number.isNaN)).toBe(true);
    });
});

describe('applyTransforms', () => {
    const forsConfig = {
        xColumnIndex: 0,
        display: {
            columnAssignments: [
                { columnIndex: 0, role: 'x' },
                { columnIndex: 1, role: 'yLeft' },
                { columnIndex: 2, role: 'reference' },
            ],
        },
        transforms: [{ type: 'reference-normalize' }],
    };

    it('normalises a real FORS shape and drops the reference series', () => {
        const parsed = {
            x: [350, 351, 352],
            ys: [
                [10, 20, 30],
                [100, 100, 100],
            ],
            seriesNames: ['tgt_count', 'ref_count'],
        };

        const out = applyTransforms(parsed, forsConfig);

        expect(out.ys).toHaveLength(1);
        expect(out.ys[0]).toEqual([0.1, 0.2, 0.3]);
        expect(out.seriesNames).toEqual(['tgt_count']);
        expect(out.x).toEqual([350, 351, 352]);
    });

    it('chains normalisation into pseudo-absorbance', () => {
        const parsed = {
            x: [350],
            ys: [[10], [100]],
            seriesNames: ['tgt', 'ref'],
        };
        const out = applyTransforms(parsed, {
            ...forsConfig,
            transforms: [{ type: 'reference-normalize' }, { type: 'log-inverse-r' }],
        });
        // R = 0.1 -> log10(1 / 0.1) = 1
        closeTo(out.ys[0][0], 1);
    });

    it('handles the single-series shape', () => {
        const out = applyTransforms(
            { x: [1, 2, 3], y: [1, 2, 4] },
            { transforms: [{ type: 'normalize-max' }] }
        );
        expect(out.y).toEqual([0.25, 0.5, 1]);
        expect(out.ys).toBeUndefined();
    });

    it('returns the input untouched when there is no chain', () => {
        const parsed = { x: [1], y: [1] };
        expect(applyTransforms(parsed, {})).toBe(parsed);
        expect(applyTransforms(parsed, { transforms: [] })).toBe(parsed);
    });

    it('skips a transform it does not know rather than throwing', () => {
        const parsed = { x: [1, 2], y: [1, 2] };
        const out = applyTransforms(parsed, {
            transforms: [{ type: 'invented-in-a-later-version' }],
        });
        expect(out.y).toEqual([1, 2]);
    });

    it('accepts bare strings as well as objects', () => {
        const out = applyTransforms(
            { x: [1, 2, 3], y: [1, 2, 4] },
            { transforms: ['normalize-max'] }
        );
        expect(out.y).toEqual([0.25, 0.5, 1]);
    });

    it('does not mutate the spectrum it was given', () => {
        const parsed = { x: [1, 2, 3], y: [1, 2, 4] };
        applyTransforms(parsed, { transforms: [{ type: 'normalize-max' }] });
        expect(parsed.y).toEqual([1, 2, 4]);
    });
});

describe('deriveAxisLabel', () => {
    it('returns the base quantity when nothing is applied', () => {
        expect(deriveAxisLabel('Reflectance (%)', { transforms: [] })).toBe(
            'Reflectance (%)'
        );
        expect(deriveAxisLabel('Counts', {})).toBe('Counts');
    });

    it('keeps the measured quantity and appends how it is shown', () => {
        // Never "log10(1/R)" alone: the reader must keep the reference point.
        expect(
            deriveAxisLabel('Reflectance (%)', {
                transforms: [{ type: 'log-inverse-r' }],
            })
        ).toBe('Reflectance (%) [log10(1/R)]');
    });

    it('does not annotate a corrective step', () => {
        // reference-normalize is what makes the label true; it does not qualify it.
        expect(
            deriveAxisLabel('Reflectance (%)', {
                transforms: [{ type: 'reference-normalize' }],
            })
        ).toBe('Reflectance (%)');
    });

    it('lists several applied steps in order', () => {
        expect(
            deriveAxisLabel('Intensity (a.u.)', {
                transforms: [
                    { type: 'smooth', window: 9 },
                    { type: 'derivative', order: 1 },
                ],
            })
        ).toBe('Intensity (a.u.) [smoothed, derivative]');
    });

    it('tolerates an empty base and unknown steps', () => {
        expect(deriveAxisLabel('', { transforms: [{ type: 'nope' }] })).toBe('');
        expect(deriveAxisLabel('Counts', { transforms: [{ type: 'nope' }] })).toBe(
            'Counts'
        );
    });
});

describe('describeChain', () => {
    it('returns null when nothing ran, so the caller can say "none"', () => {
        expect(describeChain({ transforms: [] })).toBeNull();
        expect(describeChain({})).toBeNull();
        expect(describeChain(null)).toBeNull();
    });

    it('names the applied steps in order', () => {
        expect(
            describeChain({
                transforms: [
                    { type: 'reference-normalize' },
                    { type: 'log-inverse-r' },
                ],
            })
        ).toBe('reference-normalize -> log-inverse-r');
    });

    it('ignores steps the engine does not know', () => {
        expect(
            describeChain({ transforms: [{ type: 'nope' }, 'reference-normalize'] })
        ).toBe('reference-normalize');
    });
});

describe('describeChain declares a spectral crop', () => {
    it('names the range, which filterXRange silently applies to the plot', () => {
        expect(
            describeChain({ display: { xRangeMin: 400, xRangeMax: 4000 } })
        ).toBe('cropped to 400-4000');
    });

    it('handles a one-sided range', () => {
        expect(describeChain({ display: { xRangeMin: 400 } })).toBe(
            'cropped from 400'
        );
        expect(describeChain({ display: { xRangeMax: 4000 } })).toBe(
            'cropped to 4000'
        );
    });

    it('lists the crop after the transforms that produced the values', () => {
        expect(
            describeChain({
                transforms: [{ type: 'reference-normalize' }],
                display: { xRangeMin: 400, xRangeMax: 4000 },
            })
        ).toBe('reference-normalize -> cropped to 400-4000');
    });

    it('still returns null when nothing at all is applied', () => {
        expect(describeChain({ display: {} })).toBeNull();
        expect(
            describeChain({ display: { xRangeMin: '', xRangeMax: '' } })
        ).toBeNull();
    });
});
