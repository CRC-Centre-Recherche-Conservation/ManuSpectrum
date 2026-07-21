// Minimal force-directed simulation for the Graph Explorer (framework-free, testable).
// Forces: charge repulsion (O(n^2), fine for ~12 nodes), spring links, centering, collision,
// and an optional per-node soft anchor (see `anchor` option below).
// alpha decays to a small non-zero floor so the graph stays subtly alive at rest.

const DEFAULTS = {
    charge: -900,        // node-node repulsion strength (negative = repel)
    linkDistance: 130,   // spring rest length
    linkStrength: 0.06,  // spring stiffness
    center: 0.02,        // pull toward canvas centre
    collide: 34,         // min centre-to-centre distance
    velocityDecay: 0.82, // friction
    alphaDecay: 0.02,
    alphaFloor: 0.015,   // never fully freezes
    alphaStart: 1,
    anchor: 0,           // soft pull toward a per-node (ax, ay); 0 = disabled (default, no behaviour change).
                          // Nodes without ax/ay are unaffected; fixed (setFixed) nodes ignore it.
};

export function createForceGraph(config) {
    const opts = { ...DEFAULTS, ...(config.options || {}) };
    const width = config.width || 800;
    const height = config.height || 600;
    const cx = width / 2;
    const cy = height / 2;

    const nodes = config.nodes.map((n) => ({ vx: 0, vy: 0, r: opts.collide, fx: null, fy: null, ...n }));
    const byId = new Map(nodes.map((n) => [n.id, n]));
    const links = (config.links || [])
        .map((l) => ({ source: byId.get(l.source), target: byId.get(l.target) }))
        .filter((l) => l.source && l.target);

    let alpha = opts.alphaStart;

    function tick() {
        // Charge repulsion + collision (pairwise).
        for (let i = 0; i < nodes.length; i++) {
            for (let j = i + 1; j < nodes.length; j++) {
                const a = nodes[i];
                const b = nodes[j];
                let dx = b.x - a.x;
                let dy = b.y - a.y;
                let d2 = dx * dx + dy * dy;
                if (d2 === 0) { dx = (i - j) || 1; dy = 1; d2 = 2; }
                const d = Math.sqrt(d2);
                const rep = (opts.charge * alpha) / d2;
                const fx = (dx / d) * rep;
                const fy = (dy / d) * rep;
                a.vx += fx; a.vy += fy;
                b.vx -= fx; b.vy -= fy;
                const minD = a.r + b.r;
                if (d < minD) {
                    const push = ((minD - d) / d) * 0.5;
                    a.vx -= dx * push; a.vy -= dy * push;
                    b.vx += dx * push; b.vy += dy * push;
                }
            }
        }
        // Spring links.
        for (const l of links) {
            const dx = l.target.x - l.source.x;
            const dy = l.target.y - l.source.y;
            const d = Math.hypot(dx, dy) || 1;
            const f = ((d - opts.linkDistance) * opts.linkStrength * alpha) / d;
            const fx = dx * f;
            const fy = dy * f;
            l.source.vx += fx; l.source.vy += fy;
            l.target.vx -= fx; l.target.vy -= fy;
        }
        // Centering + integrate.
        for (const n of nodes) {
            if (n.fx !== null && n.fx !== undefined) { n.x = n.fx; n.y = n.fy; n.vx = 0; n.vy = 0; continue; }
            n.vx += (cx - n.x) * opts.center * alpha;
            n.vy += (cy - n.y) * opts.center * alpha;
            if (opts.anchor && n.ax !== undefined && n.ay !== undefined) {
                n.vx += (n.ax - n.x) * opts.anchor * alpha;
                n.vy += (n.ay - n.y) * opts.anchor * alpha;
            }
            n.vx *= opts.velocityDecay;
            n.vy *= opts.velocityDecay;
            n.x += n.vx;
            n.y += n.vy;
        }
        alpha = Math.max(opts.alphaFloor, alpha - alpha * opts.alphaDecay);
        return alpha;
    }

    return {
        nodes,
        links,
        tick,
        alpha: () => alpha,
        reheat: (v = 0.8) => { alpha = Math.max(alpha, v); },
        setFixed: (id, x, y) => { const n = byId.get(id); if (n) { n.fx = x; n.fy = y; } },
        releaseFixed: (id) => { const n = byId.get(id); if (n) { n.fx = null; n.fy = null; } },
    };
}
