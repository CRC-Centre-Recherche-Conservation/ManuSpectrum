import { describe, it, expect } from 'vitest';
import {
    groupColor,
    datatypeColor,
    instanceRadius,
    contrastVsWhite,
    contrastSafeStroke,
    mixWhite,
} from './model-graph-colors';

const groups = [{ id: 'observation', color: '#10b981' }, { id: 'other', color: '#94a3b8' }];
const datatypes = [{ id: 'concept', color: '#8b5cf6' }];

describe('model-graph colors', () => {
    it('resolves a known group color', () => {
        expect(groupColor(groups, 'observation')).toBe('#10b981');
    });
    it('falls back for an unknown group', () => {
        expect(groupColor(groups, 'nope')).toBe('#94a3b8');
    });
    it('resolves a datatype color and falls back', () => {
        expect(datatypeColor(datatypes, 'concept')).toBe('#8b5cf6');
        expect(datatypeColor(datatypes, 'zzz')).toMatch(/^#[0-9a-f]{6}$/i);
    });
});

describe('instanceRadius', () => {
    it('grows with published records and stays finite at the extremes', () => {
        expect(instanceRadius(0)).toBeGreaterThan(0);
        expect(instanceRadius(80)).toBeGreaterThan(instanceRadius(0));
        expect(instanceRadius(80)).toBeLessThanOrEqual(56);
        expect(instanceRadius(100000)).toBeLessThanOrEqual(56);
    });
    it('tolerates junk input', () => {
        expect(instanceRadius(null)).toBe(instanceRadius(0));
        expect(instanceRadius(-5)).toBe(instanceRadius(0));
        expect(instanceRadius('nope')).toBe(instanceRadius(0));
    });
    it('separates the live payload values it is meant to separate', () => {
        // Analysis (80 records) must not look like Project (2). The previous
        // encoding, over field counts, put every model within 9px of every other.
        expect(instanceRadius(80) - instanceRadius(2)).toBeGreaterThan(20);
    });
});

describe('contrast helpers', () => {
    it('measures contrast against white', () => {
        expect(contrastVsWhite('#ffffff')).toBeCloseTo(1, 1);
        expect(contrastVsWhite('#000000')).toBeCloseTo(21, 0);
    });

    it('darkens the payload group hues until they clear 3:1 on white', () => {
        // These are the real /api/model-graph group colours. Green and orange
        // measure 2.54:1 and 2.85:1 raw — below the WCAG 1.4.11 floor for a
        // graphical object such as an edge stroke.
        ['#10b981', '#e67e22', '#3b82f6', '#8b5cf6', '#94a3b8'].forEach((hex) => {
            expect(contrastVsWhite(contrastSafeStroke(hex))).toBeGreaterThanOrEqual(3);
        });
    });

    it('leaves an already-compliant colour alone', () => {
        expect(contrastSafeStroke('#1d4ed8')).toBe('#1d4ed8');
    });

    it('accepts shorthand hex and passes unknown values through', () => {
        expect(contrastSafeStroke('#0f0')).toMatch(/^#[0-9a-f]{6}$/i);
        expect(contrastSafeStroke('rebeccapurple')).toBe('rebeccapurple');
    });

    it('mixWhite blends toward white and clamps', () => {
        expect(mixWhite('#000000', 0)).toBe('#ffffff');
        expect(mixWhite('#000000', 100)).toBe('#000000');
        expect(contrastVsWhite(mixWhite('#3b82f6', 20))).toBeLessThan(contrastVsWhite('#3b82f6'));
        expect(mixWhite('nope', 50)).toBe('nope');
    });
});
