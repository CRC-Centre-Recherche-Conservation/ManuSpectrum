// Integration smoke test for the Structure view.
//
// tree-layout.spec.js proves the layout maths; this proves the view actually
// RUNS — that boot() wires the fifth tab, that a `structure` payload block turns
// into SVG marks and a real <ul role="tree">, that expanding/collapsing and the
// Fields table mode work, and — most importantly — that every DB-authored string
// reaching innerHTML is escaped. A public page renders graph-designer content to
// anonymous visitors, so the escaping assertion at the bottom is the one that
// must never be deleted.

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { columnX } from 'utils/tree-layout';

vi.mock('utils/ms-nav', () => ({ default: () => {} }));

// Mirrors of the drawing constants the geometry assertions below reason about.
const GUTTER = 26;
const NG_R = 8;
const LABEL_GAP = 14;
const parseD = (p) => p.getAttribute('d').match(/-?[\d.]+/g).map(Number);

// A deliberately hostile payload: the model, field, CIDOC class and property
// names all carry markup. Nothing below may end up as live DOM.
const XSS = '<img src=x onerror=alert(1)>';

const node = (o) => ({
    cidoc_uri: '',
    property: '',
    property_code: '',
    property_uri: '',
    required: false,
    nodegroup: null,
    is_collector: false,
    cardinality: null,
    parent_nodegroup: null,
    config: {},
    cidoc: '',
    ...o,
});

const PAYLOAD = {
    language: 'en',
    stats: {
        models: 2,
        nodegroups: 2,
        nodes: 3,
        relations: 1,
        datatypes: 2,
        total_nodes: 6,
        records: 5,
        empty_models: 1,
        thesaurus_nodes: 1,
        thesaurus_pct: 33,
        cidoc_classes: 4,
        properties: 3,
        concepts: 100,
        thesauri: 2,
    },
    groups: [{ id: 'context', label_en: 'Shared context', label_fr: 'Contexte', color: '#8b5cf6' }],
    datatypes: [
        { id: 'string', label: 'String', color: '#3b82f6', count: 2 },
        { id: 'resource-instance', label: 'Resource Instance', color: '#e67e22', count: 1 },
    ],
    models: [
        {
            id: 'M1',
            name: `Person${XSS}`,
            description: '',
            group: 'context',
            cidoc: 'E21 Person',
            instances: 5,
            counts: { nodegroups: 1, nodes: 2 },
            nodegroups: [],
            structure: {
                root: 'r1',
                nodes: [
                    node({ id: 'r1', name: 'Person', datatype: 'semantic', parent: null, depth: 0 }),
                    node({
                        id: 'n1',
                        name: `Birth${XSS}`,
                        datatype: 'semantic',
                        cidoc: `E67 Birth${XSS}`,
                        // a graph designer controls ontologyclass, so the inspector's
                        // href must not accept a javascript: scheme
                        cidoc_uri: 'javascript:alert(1)',
                        parent: 'r1',
                        depth: 1,
                        nodegroup: 'ng1',
                        is_collector: true,
                        cardinality: 'n',
                        property: `P98i was born${XSS}`,
                        property_code: 'P98i',
                    }),
                    node({
                        id: 'n2',
                        name: 'Birth date',
                        datatype: 'string',
                        parent: 'n1',
                        depth: 2,
                        nodegroup: 'ng1',
                        required: true,
                        property: 'P4 has time-span',
                        property_code: 'P4',
                    }),
                    node({
                        id: 'n3',
                        name: 'Works at',
                        datatype: 'resource-instance',
                        parent: 'r1',
                        depth: 1,
                        property: 'P2 has type',
                        property_code: 'P2',
                        config: { target_graphs: ['M2'] },
                    }),
                ],
            },
        },
        {
            id: 'M2',
            name: 'Group',
            description: '',
            group: 'context',
            cidoc: 'E74 Group',
            instances: 0,
            counts: { nodegroups: 1, nodes: 1 },
            nodegroups: [],
            structure: {
                root: 'r2',
                nodes: [
                    node({ id: 'r2', name: 'Group', datatype: 'semantic', parent: null, depth: 0 }),
                    node({ id: 'n4', name: 'Label', datatype: 'string', parent: 'r2', depth: 1 }),
                ],
            },
        },
    ],
    relations: [
        { source: 'M1', target: 'M2', property: 'P107i is current or former member of', label: 'Works at', count: 1, fields: ['Works at'] },
    ],
};

const DOM = `
<p id="ms-ge-lead">fallback</p>
<dl id="ms-ge-stats"></dl>
<p id="ms-ge-volume"></p>
<div class="ms-ge-views">
  <button class="ms-ge-view is-active" data-view="matrix"></button>
  <button class="ms-ge-view" data-view="network"></button>
  <button class="ms-ge-view" data-view="structure"></button>
  <button class="ms-ge-view" data-view="datatypes"></button>
  <button class="ms-ge-view" data-view="table"></button>
</div>
<div id="ms-ge-filters"></div>
<input id="ms-ge-search"><span id="ms-ge-search-count"></span>
<div id="ms-ge-sorts"><button class="ms-ge-sort" data-sort="group"></button></div>
<div class="ms-ge-struct-tools" id="ms-ge-struct-tools" hidden>
  <select id="ms-ge-struct-model"></select>
  <input id="ms-ge-struct-q"><span id="ms-ge-struct-qcount"></span>
  <button id="ms-ge-struct-expand"></button>
  <button id="ms-ge-struct-collapse"></button>
  <button id="ms-ge-struct-outline-btn" aria-pressed="false"></button>
  <input type="checkbox" id="ms-ge-struct-semantic" checked>
  <input type="checkbox" id="ms-ge-struct-cidoc">
</div>
<div class="ms-ge-stage" id="ms-ge-stage" data-api="/api/model-graph">
  <div id="ms-ge-loading"></div><div id="ms-ge-error" hidden></div>
  <div class="ms-ge-pane" id="ms-ge-pane-matrix"><div id="ms-ge-matrix"></div></div>
  <div class="ms-ge-pane" id="ms-ge-pane-network" hidden>
    <div id="ms-ge-canvas"><svg id="ms-ge-svg"></svg><figcaption id="ms-ge-figcap"></figcaption></div>
  </div>
  <div class="ms-ge-pane" id="ms-ge-pane-structure" hidden>
    <nav id="ms-ge-struct-crumbs"></nav>
    <div class="ms-ge-struct-scroll" id="ms-ge-struct-scroll"><svg id="ms-ge-struct-svg"></svg></div>
    <figcaption id="ms-ge-struct-figcap"></figcaption>
    <div id="ms-ge-struct-outline"></div>
    <ul id="ms-ge-struct-legend"></ul>
  </div>
  <div class="ms-ge-pane" id="ms-ge-pane-datatypes" hidden><div id="ms-ge-plotly"></div></div>
  <div class="ms-ge-pane" id="ms-ge-pane-table" hidden>
    <button class="ms-ge-tbl-mode is-active" data-mode="models"></button>
    <button class="ms-ge-tbl-mode" data-mode="fields"></button>
    <div id="ms-ge-table"></div>
  </div>
  <aside id="ms-ge-drawer" hidden>
    <button id="ms-ge-drawer-close"></button>
    <div id="ms-ge-drawer-body"></div>
  </aside>
</div>
<ul id="ms-ge-legend"></ul>`;

const svg = () => document.getElementById('ms-ge-struct-svg');
const outline = () => document.getElementById('ms-ge-struct-outline');
const showStructure = () =>
    document.querySelector('.ms-ge-view[data-view="structure"]').click();

async function boot() {
    document.body.innerHTML = DOM;
    location.hash = '';
    window.matchMedia = vi.fn().mockImplementation((q) => ({
        // reduced-motion off; wide viewport on, so the SVG is drawn
        matches: q.includes('min-width'),
        addEventListener: () => {},
        removeEventListener: () => {},
    }));
    window.requestAnimationFrame = (cb) => setTimeout(cb, 0);
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => PAYLOAD });
    vi.resetModules();
    await import('./graph-explorer');
    document.dispatchEvent(new Event('DOMContentLoaded'));
    // let boot()'s awaited fetch resolve
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));
}

describe('Structure view', () => {
    beforeEach(async () => {
        await boot();
    });

    it('boots without the loading/error overlays stuck on', () => {
        expect(document.getElementById('ms-ge-loading').hidden).toBe(true);
        expect(document.getElementById('ms-ge-error').hidden).toBe(true);
    });

    it('rewrites the hero lead from live stats instead of the template fallback', () => {
        const lead = document.getElementById('ms-ge-lead').textContent;
        expect(lead).not.toBe('fallback');
        expect(lead).toContain('3'); // stats.nodes
        expect(lead).toContain('33'); // thesaurus_pct
    });

    it('reveals its per-model sub-toolbar only on the Structure tab', () => {
        expect(document.getElementById('ms-ge-struct-tools').hidden).toBe(true);
        showStructure();
        expect(document.getElementById('ms-ge-struct-tools').hidden).toBe(false);
        expect(document.getElementById('ms-ge-pane-structure').hidden).toBe(false);
        // the matrix's ordering control is meaningless here
        expect(document.getElementById('ms-ge-sorts').hidden).toBe(true);
    });

    it('fills the model combobox with every model', () => {
        showStructure();
        const opts = [...document.getElementById('ms-ge-struct-model').options];
        expect(opts).toHaveLength(2);
        // option text goes through textContent, so markup stays inert text
        expect(opts.some((o) => o.textContent.includes(XSS))).toBe(true);
    });

    it('draws discs and elbow edges for the selected model', () => {
        showStructure();
        expect(svg().querySelectorAll('.ms-ge-st-node').length).toBeGreaterThan(1);
        const edges = [...svg().querySelectorAll('.ms-ge-st-edge')];
        expect(edges.length).toBeGreaterThan(0);
        // orthogonal elbow: move, horizontal, vertical, horizontal
        expect(edges[0].getAttribute('d')).toMatch(/^M [\d.]+ [\d.]+ H [\d.]+ V [\d.]+ H [\d.]+$/);
    });

    // ── Regression: the elbow must not be drawn through its own parent ──────
    // "Birth" is an open branch with exactly ONE child, so tree-layout centres it
    // on that child and the connector's two endpoints share a y. The elbow then
    // degenerates to a single horizontal line, and while it departed from
    // `parent.x + LABEL_GAP` — the first glyph of the parent's label — that line
    // was drawn the full width of the label and rendered it struck through.
    it('departs a connector from the column gutter, never from the parent label', () => {
        showStructure();
        document.getElementById('ms-ge-struct-expand').click();
        const flat = [...svg().querySelectorAll('.ms-ge-st-edge')]
            .map(parseD)
            .filter(([, y1, , y2]) => y1 === y2);
        expect(flat.length).toBeGreaterThan(0); // the degenerate case is present
        flat.forEach(([x1, , bend, , x3]) => {
            const childX = x3 + 10; // the run stops LEAF_R + 3 short of the disc
            const depth = [1, 2, 3, 4, 5, 6, 7].find((d) => columnX(d) === childX);
            const parentX = columnX(depth - 1);
            // The vertical run always lands in the gutter at the end of the
            // parent's column. Under the bug the bend was `parentX + 28`, i.e.
            // 28px into the parent's own label.
            expect(bend).toBeGreaterThanOrEqual(childX - GUTTER);
            // The departure is a stub from the end of the parent's label, so it
            // is never the label's first glyph — which is where the bug put it.
            expect(x1).toBeGreaterThan(parentX + LABEL_GAP);
            expect(x1).toBeLessThanOrEqual(bend);
        });
    });

    // Regression: the frame was `maxX + 320`, a guess at label + CIDOC line +
    // badges + capsule. A long name carrying a `→ Target` capsule overran it and
    // the capsule was truncated at the SVG's right edge.
    it('sizes the frame so the rightmost target capsule is inside it', () => {
        showStructure();
        document.getElementById('ms-ge-struct-expand').click();
        const tx = (n) => parseFloat(/translate\(([-\d.]+)/.exec(n.getAttribute('transform'))[1]);
        const caps = [...svg().querySelectorAll('.ms-ge-st-target')];
        expect(caps.length).toBeGreaterThan(0);
        const rightmost = Math.max(
            ...caps.map(
                (c) => tx(c.parentNode) + tx(c) + +c.querySelector('rect').getAttribute('width'),
            ),
        );
        expect(+svg().getAttribute('width')).toBeGreaterThanOrEqual(rightmost);
        expect(svg().getAttribute('viewBox')).toBe(
            `0 0 ${svg().getAttribute('width')} ${svg().getAttribute('height')}`,
        );
    });

    // Regression: the chip was start-anchored at `bend + 4`, so any code longer
    // than three glyphs ran out over the disc it was labelling.
    it('keeps the property chip in the gutter, clear of the node it labels', () => {
        showStructure();
        document.getElementById('ms-ge-struct-expand').click();
        const chips = [...svg().querySelectorAll('.ms-ge-st-prop')];
        expect(chips.length).toBeGreaterThan(0);
        chips.forEach((c) => {
            // end-anchored, so `x` is the chip's RIGHT edge and it grows leftwards
            expect(c.getAttribute('text-anchor')).toBe('end');
            const childX = [1, 2, 3, 4, 5, 6, 7]
                .map((d) => columnX(d))
                .find((x) => x > +c.getAttribute('x'));
            expect(+c.getAttribute('x')).toBeLessThanOrEqual(childX - NG_R);
        });
    });

    it('renders the model root as a capsule, not a disc', () => {
        showStructure();
        const root = svg().querySelector('.ms-ge-st-node.is-root');
        expect(root).toBeTruthy();
        expect(root.querySelector('.ms-ge-st-capsule')).toBeTruthy();
        expect(root.querySelector('.ms-ge-st-disc')).toBeFalsy();
    });

    it('gives every disc a stroke so the fill is a redundant channel (WCAG 1.4.11)', () => {
        showStructure();
        const discs = [...svg().querySelectorAll('.ms-ge-st-disc')];
        expect(discs.length).toBeGreaterThan(0);
        // the stroke itself is set in pages.scss; what matters here is that the
        // fill is never the only mark — the class that carries the stroke is on.
        discs.forEach((d) => expect(d.getAttribute('class')).toContain('ms-ge-st-disc'));
    });

    // Regression: the sub-toolbar is in the DOM from first paint (merely `hidden`),
    // so its handlers were reachable before any model had been prepared and every
    // one of them threw on an undefined `byId`.
    it('survives its toolbar being used before a model is chosen', () => {
        expect(() => {
            document.getElementById('ms-ge-struct-expand').click();
            document.getElementById('ms-ge-struct-collapse').click();
            document.getElementById('ms-ge-struct-semantic').dispatchEvent(new Event('change'));
            document.getElementById('ms-ge-struct-cidoc').dispatchEvent(new Event('change'));
            const q = document.getElementById('ms-ge-struct-q');
            q.value = 'x';
            q.dispatchEvent(new Event('input'));
        }).not.toThrow();
    });

    it('gives a repeatable field group a double ring', () => {
        showStructure();
        document.getElementById('ms-ge-struct-expand').click();
        const ng = [...svg().querySelectorAll('.ms-ge-st-node')].find(
            (g) => g.querySelectorAll('.ms-ge-st-ring').length === 2,
        );
        expect(ng).toBeTruthy(); // "Birth" is cardinality n
    });

    it('dims the two common properties and leaves the rest at full strength', () => {
        showStructure();
        document.getElementById('ms-ge-struct-expand').click();
        // The chip carries a <title> child for the hover tooltip, so read the
        // label's own text node rather than textContent.
        const chips = [...svg().querySelectorAll('.ms-ge-st-prop')];
        const code = (c) => c.firstChild.nodeValue;
        const p2 = chips.find((c) => code(c) === 'P2');
        const p98 = chips.find((c) => code(c) === 'P98i');
        expect(p2.getAttribute('class')).toContain('is-common');
        expect(p98.getAttribute('class')).not.toContain('is-common');
    });

    it('carries the full property text as a hover tooltip on the chip', () => {
        showStructure();
        document.getElementById('ms-ge-struct-expand').click();
        const chip = [...svg().querySelectorAll('.ms-ge-st-prop')].find(
            (c) => c.firstChild.nodeValue === 'P98i',
        );
        // <title> is set via textContent, so the payload's markup stays inert.
        expect(chip.querySelector('title').textContent).toContain('was born');
    });

    it('shows a target capsule on a resource-instance node', () => {
        showStructure();
        const cap = svg().querySelector('.ms-ge-st-target');
        expect(cap).toBeTruthy();
        expect(cap.dataset.target).toBe('M2');
    });

    it('always renders a real <ul role="tree"> with APG attributes', () => {
        showStructure();
        const tree = outline().querySelector('[role="tree"]');
        expect(tree).toBeTruthy();
        const items = outline().querySelectorAll('[role="treeitem"]');
        expect(items.length).toBeGreaterThan(1);
        items.forEach((li) => {
            expect(li.getAttribute('aria-level')).toBeTruthy();
            expect(li.getAttribute('aria-posinset')).toBeTruthy();
            expect(li.getAttribute('aria-setsize')).toBeTruthy();
        });
        // exactly one tab stop into the tree (roving tabindex)
        expect([...items].filter((i) => i.tabIndex === 0)).toHaveLength(1);
    });

    it('gives the SVG a real visible text equivalent quoting the model totals', () => {
        showStructure();
        const cap = document.getElementById('ms-ge-struct-figcap').textContent;
        expect(cap).toContain('2'); // 2 data fields under the Person root
        expect(cap).toContain('2'); // nested 2 levels deep
        // and the outline carries the same sentence as its accessible name
        const tree = outline().querySelector('[role="tree"]');
        expect(tree.getAttribute('aria-label')).toBe(cap);
    });

    it('expands and collapses the whole tree', () => {
        showStructure();
        document.getElementById('ms-ge-struct-expand').click();
        const expanded = svg().querySelectorAll('.ms-ge-st-node').length;
        document.getElementById('ms-ge-struct-collapse').click();
        expect(svg().querySelectorAll('.ms-ge-st-node').length).toBeLessThan(expanded);
    });

    it('dims non-matching nodes on search rather than removing them', () => {
        showStructure();
        const q = document.getElementById('ms-ge-struct-q');
        q.value = 'P98i'; // a property code is a real query for this audience
        q.dispatchEvent(new Event('input'));
        expect(svg().querySelector('.ms-ge-st-node.is-hit')).toBeTruthy();
        expect(svg().querySelector('.ms-ge-st-node.is-dim')).toBeTruthy();
        expect(document.getElementById('ms-ge-struct-qcount').textContent).toBeTruthy();
    });

    it('reports a no-match search in the status region', () => {
        showStructure();
        const q = document.getElementById('ms-ge-struct-q');
        q.value = 'zzzznothing';
        q.dispatchEvent(new Event('input'));
        const count = document.getElementById('ms-ge-struct-qcount');
        expect(count.classList.contains('is-none')).toBe(true);
    });

    it('opens the node inspector with a header distinct from the model view', () => {
        showStructure();
        const disc = [...svg().querySelectorAll('.ms-ge-st-node')].find(
            (g) => !g.classList.contains('is-root'),
        );
        disc.dispatchEvent(new Event('click', { bubbles: true }));
        const head = document.querySelector('.ms-ge-drawer-head');
        expect(head.classList.contains('is-node')).toBe(true);
        expect(document.querySelector('.ms-ge-insp-eyebrow')).toBeTruthy();
    });

    it('refuses a javascript: scheme in a CIDOC URI from the payload', () => {
        showStructure();
        const birth = [...svg().querySelectorAll('.ms-ge-st-node')].find(
            (g) => g.querySelectorAll('.ms-ge-st-ring').length === 2,
        );
        birth.dispatchEvent(new Event('click', { bubbles: true }));
        const links = [...document.querySelectorAll('.ms-ge-insp a')];
        links.forEach((a) => expect(a.getAttribute('href')).toMatch(/^https?:\/\//i));
        // the class is still shown, just not as a link
        expect(document.querySelector('.ms-ge-insp').textContent).toContain('E67 Birth');
    });

    it('writes a deep link naming the view and the node', () => {
        showStructure();
        const disc = [...svg().querySelectorAll('.ms-ge-st-node')].find(
            (g) => !g.classList.contains('is-root'),
        );
        disc.dispatchEvent(new Event('click', { bubbles: true }));
        expect(location.hash).toContain('view=structure');
        expect(location.hash).toContain('node=');
    });

    it('flattens every model into the Fields table mode', () => {
        document.querySelector('.ms-ge-tbl-mode[data-mode="fields"]').click();
        const table = document.querySelector('.ms-ge-tbl-fields');
        expect(table).toBeTruthy();
        // one row per node, roots excluded (4 + 2 nodes, 2 roots => 4 rows)
        expect(table.querySelectorAll('tbody tr')).toHaveLength(4);
    });

    // ── the one that must never be deleted ──────────────────────────────────
    it('escapes DB-authored content everywhere it reaches innerHTML', () => {
        showStructure();
        document.getElementById('ms-ge-struct-expand').click();
        const disc = [...svg().querySelectorAll('.ms-ge-st-node')].find(
            (g) => !g.classList.contains('is-root'),
        );
        disc.dispatchEvent(new Event('click', { bubbles: true }));
        document.querySelector('.ms-ge-tbl-mode[data-mode="fields"]').click();
        // The payload plants `<img src=x onerror=...>` in a model name, a field
        // name, a CIDOC class and a property. If any of it were interpolated raw,
        // an <img> element would exist in the document.
        expect(document.querySelectorAll('img')).toHaveLength(0);
        // ...and the text is still there, as text.
        expect(document.body.textContent).toContain('<img src=x');
    });
});
