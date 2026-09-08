import { describe, it, expect } from 'vitest';
import { BASE_VIEW, VIEWS_BY_PRESET, findView, viewsFor } from './xy-views';
import { applyTransforms, deriveAxisLabel } from './xy-transforms';

describe('view palettes', () => {
    it('always opens on the base quantity', () => {
        for (const key of Object.keys(VIEWS_BY_PRESET)) {
            const views = viewsFor({ presetKey: key });
            expect(views[0].key).toBe(BASE_VIEW);
            expect(views[0].transforms).toEqual([]);
        }
    });

    it('offers nothing but the base for a hand-made configuration', () => {
        // No preset key: guessing which lenses suit an unknown file would be
        // worse than offering none.
        expect(viewsFor({}).map((v) => v.key)).toEqual([BASE_VIEW]);
        expect(viewsFor(null).map((v) => v.key)).toEqual([BASE_VIEW]);
    });

    it('keeps a lens out of the instrument families it means nothing for', () => {
        // Kubelka-Munk models diffuse reflectance; it has no meaning applied to
        // an XRF count spectrum or a mass spectrum.
        const keys = (preset) => viewsFor({ presetKey: preset }).map((v) => v.key);
        expect(keys('xrf')).not.toContain('kubelka-munk');
        expect(keys('maldi')).not.toContain('kubelka-munk');
        expect(keys('fors')).toContain('kubelka-munk');
    });

    it('offers derivatives only where the field reads them', () => {
        const hasDerivative = (preset) =>
            viewsFor({ presetKey: preset }).some((v) =>
                v.key.startsWith('derivative')
            );
        expect(hasDerivative('fors')).toBe(true);
        expect(hasDerivative('raman')).toBe(false);
        expect(hasDerivative('xrf')).toBe(false);
    });

    it('never offers smoothing', () => {
        // A Savitzky-Golay window has to match the instrument's resolution, and
        // a reader did not set up the acquisition.
        for (const views of Object.values(VIEWS_BY_PRESET)) {
            for (const v of views) {
                for (const step of v.transforms) {
                    expect(step.type).not.toBe('smooth');
                }
            }
        }
    });

    it('falls back to the base rather than throwing on an unknown key', () => {
        expect(findView({ presetKey: 'fors' }, 'nope').key).toBe(BASE_VIEW);
    });
});

describe('a view composes after the configuration', () => {
    const spectrum = { x: [1, 2, 3], y: [2, 4, 8] };

    it('leaves the spectrum untouched on the base view', () => {
        const base = findView({ presetKey: 'fors' }, BASE_VIEW);
        expect(applyTransforms(spectrum, { transforms: base.transforms })).toEqual(
            spectrum
        );
    });

    it('applies the lens and says so on the axis', () => {
        const lens = findView({ presetKey: 'xrf' }, 'normalize-max');
        const seen = applyTransforms(spectrum, { transforms: lens.transforms });

        expect(seen.y).toEqual([0.25, 0.5, 1]);
        expect(deriveAxisLabel('Counts', { transforms: lens.transforms })).toBe(
            'Counts [normalised to max]'
        );
    });
});
