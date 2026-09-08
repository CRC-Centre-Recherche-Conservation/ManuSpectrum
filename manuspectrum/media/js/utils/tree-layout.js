// Deterministic layered tree layout for the Graph Explorer's Structure view.
//
// This exists SPECIFICALLY so that the Structure view is not drawn with
// utils/force-graph.js. Every ManuSpectrum resource model is a strict tree
// (`edges == nodes - 1`, exactly one root, no cycles, no cross-links — verified
// against the live database for all 12 models). A force simulation is a tool for
// *discovering* unknown structure; applied to a known tree it re-derives the
// shape badly and, fatally, non-deterministically — a different picture on every
// page load. The Graph Explorer is a public reference page that researchers
// screenshot and cite, so a layout that cannot be reproduced is disqualifying.
//
// The pass below is O(n), allocation-light, and a pure function of its input:
// same tree + same expansion state => same coordinates, always.
//
//   1. DFS the tree, children already sorted by name (stable ordering)
//   2. every visible LEAF (or collapsed branch):  y = slot++ * rowPitch
//   3. every visible INTERNAL node:               y = (firstChild.y + lastChild.y) / 2
//   4. every node:                                x = sum(colWidth(0..depth-1))
//
// Drawn this way with orthogonal elbow edges, edge crossings are mathematically
// impossible — which is the whole reason not to simulate.

export const ROW_PITCH = 30;
// Columns taper so a depth-7 branch (Person, Component) still gets a readable run.
export const COL_WIDTHS = [210, 190, 170, 155, 145, 135, 130];
export const COL_TAIL = 130;
export const COL_X0 = 26;

export function columnX(depth, widths = COL_WIDTHS, tail = COL_TAIL, x0 = COL_X0) {
    let x = x0;
    for (let i = 0; i < depth; i += 1) x += i < widths.length ? widths[i] : tail;
    return x;
}

/**
 * @param {object} root         the node to draw at depth 0 (may be a re-root)
 * @param {(node) => Array<{node: object, via: string[]}>} kidsOf
 *        children as DRAWN — already name-sorted, with structural nodes spliced
 *        out and their property codes folded into `via` when that toggle is off
 * @param {(node) => boolean} isOpen  whether a node's children are shown
 * @param {object} [opts]  { rowPitch, x }  (`x` lets tests inject a simple ramp)
 * @returns {{rows: Array, slots: number}} rows in PRE-ORDER (parents first)
 */
export function layoutTree(root, kidsOf, isOpen, opts) {
    const o = opts || {};
    const rowPitch = o.rowPitch || ROW_PITCH;
    const xOf = o.x || ((depth) => columnX(depth));
    const rows = [];
    if (!root) return { rows, slots: 0 };
    let slot = 0;

    const visit = (node, depth, via, posinset, setsize) => {
        const kidList = kidsOf(node) || [];
        const expandable = kidList.length > 0;
        const open = expandable && isOpen(node);
        const row = {
            node,
            depth,
            via,
            expandable,
            open,
            posinset,
            setsize,
            x: xOf(depth),
            y: 0,
        };
        rows.push(row); // pre-order: a parent is always emitted before its children
        if (!open) {
            row.y = slot * rowPitch;
            slot += 1;
        } else {
            const childRows = kidList.map((k, i) =>
                visit(k.node, depth + 1, k.via || [], i + 1, kidList.length),
            );
            row.y = (childRows[0].y + childRows[childRows.length - 1].y) / 2;
        }
        return row;
    };

    visit(root, 0, [], 1, 1);
    return { rows, slots: slot };
}
