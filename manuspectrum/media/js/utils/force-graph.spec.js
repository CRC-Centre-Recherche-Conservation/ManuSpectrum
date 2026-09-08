import { describe, it, expect } from 'vitest';
import { createForceGraph } from './force-graph';

function dist(a, b) {
    return Math.hypot(a.x - b.x, a.y - b.y);
}

describe('createForceGraph', () => {
    it('alpha decays toward the floor over ticks', () => {
        const sim = createForceGraph({
            nodes: [{ id: 'a', x: 0, y: 0 }, { id: 'b', x: 10, y: 0 }],
            links: [{ source: 'a', target: 'b' }],
            width: 200, height: 200,
        });
        const a0 = sim.alpha();
        for (let i = 0; i < 50; i++) sim.tick();
        expect(sim.alpha()).toBeLessThan(a0);
        expect(sim.alpha()).toBeGreaterThan(0); // non-zero floor keeps it subtly alive
    });

    it('linked nodes settle near the spring rest length', () => {
        const sim = createForceGraph({
            nodes: [{ id: 'a', x: -300, y: 0 }, { id: 'b', x: 300, y: 0 }],
            links: [{ source: 'a', target: 'b' }],
            width: 400, height: 400,
            options: { linkDistance: 120 },
        });
        for (let i = 0; i < 400; i++) sim.tick();
        const d = dist(sim.nodes[0], sim.nodes[1]);
        expect(d).toBeGreaterThan(60);
        expect(d).toBeLessThan(220); // pulled in from 600 toward ~120
    });

    it('disconnected nodes repel (move apart from near-coincident start)', () => {
        const sim = createForceGraph({
            nodes: [{ id: 'a', x: 0, y: 0 }, { id: 'b', x: 1, y: 0 }],
            links: [],
            width: 400, height: 400,
        });
        const before = dist(sim.nodes[0], sim.nodes[1]);
        for (let i = 0; i < 60; i++) sim.tick();
        expect(dist(sim.nodes[0], sim.nodes[1])).toBeGreaterThan(before);
    });

    it('a fixed node stays put while others move', () => {
        const sim = createForceGraph({
            nodes: [{ id: 'a', x: 0, y: 0 }, { id: 'b', x: 50, y: 0 }],
            links: [{ source: 'a', target: 'b' }],
            width: 400, height: 400,
        });
        sim.setFixed('a', 0, 0);
        for (let i = 0; i < 100; i++) sim.tick();
        expect(sim.nodes[0].x).toBe(0);
        expect(sim.nodes[0].y).toBe(0);
    });

    it('reheat raises alpha back up', () => {
        const sim = createForceGraph({
            nodes: [{ id: 'a', x: 0, y: 0 }, { id: 'b', x: 10, y: 0 }],
            links: [], width: 200, height: 200,
        });
        for (let i = 0; i < 100; i++) sim.tick();
        const low = sim.alpha();
        sim.reheat();
        expect(sim.alpha()).toBeGreaterThan(low);
    });

    // The pre-existing `center` force pulls every node toward the canvas centre, and in this
    // scenario the anchor happens to lie centre-ward too — so a naive "distance to anchor
    // shrank a lot" assertion passes even with the anchor force deleted entirely (measured:
    // centering alone gets the node to ~246px vs a ~247px before/after*0.5 threshold, a 0.55%
    // margin). To actually prove the anchor force is doing the work, run the identical
    // deterministic scenario twice — once with `anchor: 0` (control, anchor force disabled)
    // and once with `anchor: 0.2` (treatment) — and assert the treatment ends up substantially
    // closer to the anchor than the control does. Centering affects both runs equally, so it
    // cancels out of the comparison; only the anchor force can produce the gap. Do not "simplify"
    // this back to a single-run before/after check — that is precisely the form that was proven
    // not to discriminate.
    it('anchor pulls a node toward its anchor point (vs an anchor:0 control)', () => {
        const scenario = (anchorStrength) => createForceGraph({
            nodes: [
                { id: 'a', x: 0, y: 0, ax: 350, ay: 350 },
                { id: 'b', x: 400, y: 400 },
            ],
            links: [],
            width: 400, height: 400,
            options: { anchor: anchorStrength },
        });
        const anchor = { x: 350, y: 350 };

        const control = scenario(0);
        for (let i = 0; i < 300; i++) control.tick();
        const controlDist = dist(control.nodes[0], anchor);

        const anchored = scenario(0.2);
        for (let i = 0; i < 300; i++) anchored.tick();
        const anchoredDist = dist(anchored.nodes[0], anchor);

        // Anchored run must land substantially closer than the control, AND within an absolute
        // bound the control cannot meet (control measured ~246px, anchored ~41px for this scenario).
        expect(anchoredDist).toBeLessThan(controlDist * 0.5);
        expect(anchoredDist).toBeLessThan(100);
    });

    it('anchor is opt-in and pinning still overrides it', () => {
        const sim = createForceGraph({
            nodes: [
                { id: 'a', x: 0, y: 0 }, // no ax/ay: must be unaffected by anchor, but still move via other forces
                { id: 'b', x: 50, y: 0, ax: 350, ay: 350 }, // will be pinned despite having an anchor
            ],
            links: [{ source: 'a', target: 'b' }],
            width: 400, height: 400,
            options: { anchor: 0.2 },
        });
        sim.setFixed('b', 50, 0);
        for (let i = 0; i < 300; i++) sim.tick();

        // Node without ax/ay: not NaN, and still moved under charge/link/centering forces.
        // (`toBeGreaterThan(0)` here is only a smoke/NaN guard — any nonzero force, including
        // the always-on centering force, would satisfy it. It is NOT evidence that the anchor
        // is being skipped; that claim rests on the dedicated control-vs-treatment test above.)
        expect(Number.isNaN(sim.nodes[0].x)).toBe(false);
        expect(Number.isNaN(sim.nodes[0].y)).toBe(false);
        expect(dist(sim.nodes[0], { x: 0, y: 0 })).toBeGreaterThan(0);

        // Pinned node stays exactly at its pinned coordinates, ignoring its own anchor.
        expect(sim.nodes[1].x).toBe(50);
        expect(sim.nodes[1].y).toBe(0);
    });
});
