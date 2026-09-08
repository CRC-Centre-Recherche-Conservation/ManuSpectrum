import { describe, it, expect } from 'vitest';
import { layoutTree, columnX, ROW_PITCH, COL_WIDTHS, COL_X0 } from './tree-layout';

// A small stand-in for a real model: one root, two branches, five leaves.
//
//   root
//   ├── a        (branch)
//   │   ├── a1
//   │   └── a2
//   ├── b
//   └── c        (branch)
//       ├── c1
//       └── c2
const TREE = {
    root: ['a', 'b', 'c'],
    a: ['a1', 'a2'],
    c: ['c1', 'c2'],
};
const node = (id) => ({ id, name: id });
const kidsOf = (n) => (TREE[n.id] || []).map((id) => ({ node: node(id), via: [] }));
const allOpen = () => true;
const run = (isOpen, opts) => layoutTree(node('root'), kidsOf, isOpen, opts);
const yOf = (rows, id) => rows.find((r) => r.node.id === id).y;

describe('columnX', () => {
    it('starts at the left margin and accumulates the tapered widths', () => {
        expect(columnX(0)).toBe(COL_X0);
        expect(columnX(1)).toBe(COL_X0 + COL_WIDTHS[0]);
        expect(columnX(3)).toBe(COL_X0 + COL_WIDTHS[0] + COL_WIDTHS[1] + COL_WIDTHS[2]);
    });

    it('falls back to the tail width past the end of the ramp, so depth 7+ still lays out', () => {
        const deep = columnX(9);
        expect(deep).toBeGreaterThan(columnX(8));
        expect(deep - columnX(8)).toBe(130);
    });
});

describe('layoutTree', () => {
    it('returns an empty result for a missing root rather than throwing', () => {
        expect(layoutTree(null, kidsOf, allOpen)).toEqual({ rows: [], slots: 0 });
    });

    it('emits rows in pre-order: every parent before its children', () => {
        const { rows } = run(allOpen);
        const order = rows.map((r) => r.node.id);
        expect(order).toEqual(['root', 'a', 'a1', 'a2', 'b', 'c', 'c1', 'c2']);
    });

    it('packs leaves onto consecutive slots, top to bottom in DFS order', () => {
        const { rows, slots } = run(allOpen);
        expect(slots).toBe(5); // a1 a2 b c1 c2
        expect(yOf(rows, 'a1')).toBe(0 * ROW_PITCH);
        expect(yOf(rows, 'a2')).toBe(1 * ROW_PITCH);
        expect(yOf(rows, 'b')).toBe(2 * ROW_PITCH);
        expect(yOf(rows, 'c1')).toBe(3 * ROW_PITCH);
        expect(yOf(rows, 'c2')).toBe(4 * ROW_PITCH);
    });

    it('centres an internal node between its first and last child', () => {
        const { rows } = run(allOpen);
        expect(yOf(rows, 'a')).toBe((yOf(rows, 'a1') + yOf(rows, 'a2')) / 2);
        expect(yOf(rows, 'c')).toBe((yOf(rows, 'c1') + yOf(rows, 'c2')) / 2);
        expect(yOf(rows, 'root')).toBe((yOf(rows, 'a') + yOf(rows, 'c')) / 2);
    });

    it('places depth on the x axis only — y never depends on depth', () => {
        const { rows } = run(allOpen);
        rows.forEach((r) => expect(r.x).toBe(columnX(r.depth)));
    });

    it('gives a collapsed branch a single slot and hides its subtree', () => {
        const { rows, slots } = run((n) => n.id !== 'a');
        expect(rows.map((r) => r.node.id)).toEqual(['root', 'a', 'b', 'c', 'c1', 'c2']);
        expect(slots).toBe(4); // a (collapsed, one slot) b c1 c2
        const a = rows.find((r) => r.node.id === 'a');
        expect(a.expandable).toBe(true);
        expect(a.open).toBe(false);
    });

    it('marks a childless node as not expandable', () => {
        const { rows } = run(allOpen);
        expect(rows.find((r) => r.node.id === 'b').expandable).toBe(false);
    });

    it('sets aria-friendly posinset/setsize from the drawn sibling list', () => {
        const { rows } = run(allOpen);
        const a2 = rows.find((r) => r.node.id === 'a2');
        expect(a2.posinset).toBe(2);
        expect(a2.setsize).toBe(2);
        const c = rows.find((r) => r.node.id === 'c');
        expect(c.posinset).toBe(3);
        expect(c.setsize).toBe(3);
    });

    // THE POINT OF THIS MODULE. A force simulation would fail this test by
    // construction; that is exactly why the Structure view does not use one.
    it('is deterministic — identical input yields byte-identical coordinates', () => {
        const a = run(allOpen).rows.map((r) => [r.node.id, r.x, r.y]);
        const b = run(allOpen).rows.map((r) => [r.node.id, r.x, r.y]);
        expect(a).toEqual(b);
    });

    // Orthogonal elbows between a parent centred on its children and those
    // children cannot cross, so it is enough to prove the invariant the drawing
    // relies on: within a sibling group, y is strictly increasing.
    it('never lets siblings share or invert a row (the no-crossing invariant)', () => {
        const { rows } = run(allOpen);
        const byParent = new Map();
        rows.forEach((r) => {
            const kids = kidsOf(r.node).map((k) => k.node.id);
            if (kids.length) byParent.set(r.node.id, kids);
        });
        byParent.forEach((kids) => {
            const ys = kids.map((id) => yOf(rows, id));
            for (let i = 1; i < ys.length; i += 1) expect(ys[i]).toBeGreaterThan(ys[i - 1]);
        });
    });

    it('honours an injected row pitch and x ramp', () => {
        const { rows } = run(allOpen, { rowPitch: 10, x: (d) => d * 100 });
        expect(yOf(rows, 'a2')).toBe(10);
        expect(rows.find((r) => r.node.id === 'a1').x).toBe(200);
    });
});
