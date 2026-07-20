import { describe, it, expect } from 'vitest';
import { groupColor, datatypeColor, nodeRadius } from './model-graph-colors';

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
    it('node radius grows monotonically with field count', () => {
        expect(nodeRadius(0)).toBeGreaterThan(0);
        expect(nodeRadius(50)).toBeGreaterThan(nodeRadius(5));
    });
});
