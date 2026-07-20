import arches from 'arches';
import initMsNav from 'utils/ms-nav';
import { createForceGraph } from 'utils/force-graph';
import { groupColor, datatypeColor, nodeRadius } from 'utils/model-graph-colors';

const SVGNS = 'http://www.w3.org/2000/svg';
const el = (id) => document.getElementById(id);
const svgEl = (tag, attrs) => {
    const n = document.createElementNS(SVGNS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, v));
    return n;
};
const t = (k, fallback) => (arches.translations && arches.translations[k]) || fallback;

// ---------------------------------------------------------------------------
// LAYOUT TUNING — measured against the real payload, do NOT change casually.
// The model graph is NEAR-COMPLETE (12 models / 70 relations), so a plain force
// layout collapses into a central hairball (~274x238 px in a 900x560 canvas) and
// simply raising repulsion pushes nodes out of bounds instead of spreading them.
// The fix is a soft GROUP ANCHOR per node: the four atelier groupings settle into
// visually distinct clusters (which is also the differentiation the page is for).
// Measured with these values on the live data: span 518x308, 4 clusters ~195px
// apart, zero node overlaps, all nodes in bounds, alpha resting at its floor.
const MS_GROUP_ANCHORS = {
    'studied-object': [0.16, 0.22],
    observation: [0.84, 0.22],
    context: [0.16, 0.80],
    transformations: [0.84, 0.80],
};
const MS_FORCE_OPTIONS = {
    charge: -2200,
    linkDistance: 180,
    center: 0.004, // weak: the anchors do the placing
    collide: 52,
    anchor: 0.26,
};
// ---------------------------------------------------------------------------

// SECURITY: every value that originates from the /api/model-graph payload is
// DB-authored (graph/field names, CIDOC classes, descriptions, nodegroup names,
// group colors/labels). It reaches an anonymous public page, so it MUST be
// escaped before going into innerHTML — otherwise a graph designer can plant
// stored XSS. Values written via textContent (SVG node labels) or via the DOM
// setAttribute API (SVG node/edge attributes) are already safe and are not
// re-escaped below.
const esc = (v) =>
    String(v ?? '').replace(/[&<>"']/g, (c) =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
    );

// Groups carry both label_en/label_fr from the payload; pick the one matching
// the page's active language (data.language, set server-side from the request).
function groupLabel(data, group) {
    if (!group) return '';
    const preferred = data.language === 'fr' ? group.label_fr : group.label_en;
    return preferred || group.label_en || group.label_fr || group.id || '';
}

function revealOnScroll() {
    const els = document.querySelectorAll('.reveal');
    if (!('IntersectionObserver' in window)) {
        els.forEach((e) => e.classList.add('is-visible'));
        return;
    }
    const io = new IntersectionObserver(
        (entries) => {
            entries.forEach((en) => {
                if (en.isIntersecting) {
                    en.target.classList.add('is-visible');
                    io.unobserve(en.target);
                }
            });
        },
        { threshold: 0.15 },
    );
    els.forEach((e) => io.observe(e));
}

// Module-scoped (not on `window`) so nothing leaks to the global object; set in
// render() and closed over by openDrawer's relation-button handler (see finding 11).
let currentGraph = null;
// Element that opened the drawer (a node <g>, the search input, a relation button,
// or the canvas as a fallback) — focus returns here when the drawer closes.
let drawerTrigger = null;
let drawerChromeWired = false;

async function boot() {
    initMsNav();
    revealOnScroll();
    const canvas = el('ms-ge-canvas');
    if (!canvas) return;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    try {
        const res = await fetch(canvas.dataset.api, { headers: { Accept: 'application/json' } });
        if (!res.ok) throw new Error(res.status);
        const data = await res.json();
        el('ms-ge-loading').hidden = true;
        render(data, reduce);
    } catch (e) {
        el('ms-ge-loading').hidden = true;
        el('ms-ge-error').hidden = false;
    }
}

function render(data, reduce) {
    renderStats(data);
    renderLegend(data);
    renderFilters(data);
    renderList(data);
    const graph = new GraphView(data, reduce);
    currentGraph = graph;
    graph.mount();
    wireViews(data, graph);
    wireSearch(data, graph);
    openFromHash(data);
}

// Finding 5: the deep-link written by openDrawer (`#model=<id>`) was write-only.
// On load, once the payload is rendered, read it back and open the matching drawer.
function openFromHash(data) {
    const match = /model=([^&]+)/.exec(location.hash || '');
    if (!match) return;
    const id = decodeURIComponent(match[1]);
    const model = (data.models || []).find((m) => m.id === id);
    if (model) openDrawer(model, data);
}

function renderStats(data) {
    const s = data.stats || {};
    const items = [
        [s.models, t('msGeModels', 'models')],
        [s.relations, t('msGeStatRelations', 'relations')],
        [s.nodes, t('msGeStatFields', 'fields')],
        [s.datatypes, t('msGeStatDatatypes', 'datatypes')],
    ];
    el('ms-ge-stats').innerHTML = items
        .map(([v, l]) => `<div class="ms-ge-stat"><span>${v ?? '—'}</span><em>${esc(l)}</em></div>`)
        .join('');
}

function renderLegend(data) {
    el('ms-ge-legend').innerHTML = (data.groups || [])
        .filter((g) => (data.models || []).some((m) => m.group === g.id))
        .map((g) => `<li><i style="background:${esc(g.color)}"></i>${esc(groupLabel(data, g))}</li>`)
        .join('');
}

function renderFilters(data) {
    const box = el('ms-ge-filters');
    box.innerHTML = (data.groups || [])
        .filter((g) => (data.models || []).some((m) => m.group === g.id))
        .map(
            (g) =>
                `<button class="ms-ge-filter is-on" data-group="${esc(g.id)}" style="--c:${esc(g.color)}" aria-pressed="true">${esc(groupLabel(data, g))}</button>`,
        )
        .join('');
}

function renderList(data) {
    el('ms-ge-list').innerHTML = (data.models || [])
        .map(
            (m) =>
                `<div class="ms-ge-list-item"><strong>${esc(m.name)}</strong> — ${esc(m.cidoc)} · ${m.counts.nodes} ${esc(t('msGeStatFields', 'fields'))}</div>`,
        )
        .join('');
}

class GraphView {
    constructor(data, reduce) {
        this.data = data;
        this.reduce = reduce;
        this.svg = el('ms-ge-svg');
        this.activeGroups = new Set((data.groups || []).map((g) => g.id));
        this.raf = null;
    }

    mount() {
        const rect = this.svg.getBoundingClientRect();
        this.w = rect.width || 900;
        this.h = rect.height || 600;
        this.svg.setAttribute('viewBox', `0 0 ${this.w} ${this.h}`);

        // Seed positions on a circle (deterministic — no Math.random for layout stability),
        // and give each node its GROUP ANCHOR (see MS_GROUP_ANCHORS / MS_FORCE_OPTIONS above).
        const models = this.data.models || [];
        const R = Math.min(this.w, this.h) * 0.34;
        const nodes = models.map((m, i) => {
            const a = (i / models.length) * Math.PI * 2;
            const anchor = MS_GROUP_ANCHORS[m.group] || [0.5, 0.5];
            return {
                id: m.id,
                x: this.w / 2 + Math.cos(a) * R,
                y: this.h / 2 + Math.sin(a) * R,
                r: nodeRadius(m.counts.nodes),
                ax: anchor[0] * this.w,
                ay: anchor[1] * this.h,
                model: m,
            };
        });
        const links = (this.data.relations || []).map((r) => ({ source: r.source, target: r.target, rel: r }));

        this.sim = createForceGraph({
            nodes, links, width: this.w, height: this.h,
            options: MS_FORCE_OPTIONS,
        });
        this.buildDom(nodes, links);
        if (this.reduce) { for (let i = 0; i < 300; i++) this.sim.tick(); this.paint(); }
        else this.loop();
        this.wireDrag();
        this.wireResize();
    }

    // Finding 6: mount() bakes this.w/this.h into the viewBox once; toSvg() (in
    // wireDrag) scales live getBoundingClientRect() against those stale values,
    // so drag coordinates desync after a window resize. Re-read the rect and
    // refresh this.w/this.h + the viewBox on resize (debounced; no re-layout).
    wireResize() {
        let timer = null;
        this.resizeHandler = () => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                const rect = this.svg.getBoundingClientRect();
                this.w = rect.width || this.w;
                this.h = rect.height || this.h;
                this.svg.setAttribute('viewBox', `0 0 ${this.w} ${this.h}`);
            }, 150);
        };
        window.addEventListener('resize', this.resizeHandler);
    }

    buildDom(nodes, links) {
        this.svg.innerHTML = '';
        this.gEdges = svgEl('g', { class: 'ms-ge-edges' });
        this.gNodes = svgEl('g', { class: 'ms-ge-nodes' });
        this.svg.appendChild(this.gEdges);
        this.svg.appendChild(this.gNodes);

        // Edge titles are set via textContent (safe, see SECURITY note above).
        this.edgeEls = links.map((l) => {
            const p = svgEl('path', { class: 'ms-ge-edge', fill: 'none' });
            const title = svgEl('title', {});
            title.textContent = l.rel.property || '';
            p.appendChild(title);
            this.gEdges.appendChild(p);
            return { p, l };
        });

        // Node circles/labels are built via the DOM API (setAttribute/textContent),
        // not innerHTML strings, so they are already safe (see SECURITY note above).
        this.nodeEls = nodes.map((n) => {
            // aria-label goes through setAttribute (SVGNS DOM API), not innerHTML —
            // already safe per the SECURITY note above, no esc() needed.
            const g = svgEl('g', {
                class: 'ms-ge-node', 'data-id': n.id, tabindex: '0', role: 'button',
                'aria-label': n.model.name,
            });
            const c = svgEl('circle', { r: n.r, fill: groupColor(this.data.groups, n.model.group) });
            const label = svgEl('text', { class: 'ms-ge-node-label', 'text-anchor': 'middle', dy: n.r + 16 });
            label.textContent = n.model.name;
            g.appendChild(c);
            g.appendChild(label);
            // Finding 4: wireDrag() calls setPointerCapture, so the synthesized click
            // after a drag is redirected to this element regardless of pointer travel.
            // n._dragMoved (set in wireDrag) tells us whether this click followed a
            // real drag; if so, swallow it once and skip opening the drawer.
            g.addEventListener('click', () => {
                if (n._dragMoved) { n._dragMoved = false; return; }
                openDrawer(n.model, this.data, g);
            });
            // Finding 7: role="button" must also respond to Space, not just Enter.
            g.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
                    e.preventDefault();
                    openDrawer(n.model, this.data, g);
                }
            });
            g.addEventListener('mouseenter', () => this.highlight(n.id, true));
            g.addEventListener('mouseleave', () => this.highlight(n.id, false));
            this.gNodes.appendChild(g);
            return { g, c, n };
        });
    }

    paint() {
        for (const { p, l } of this.edgeEls) {
            const s = l.source; const tg = l.target;
            const mx = (s.x + tg.x) / 2; const my = (s.y + tg.y) / 2 - 30;
            p.setAttribute('d', `M ${s.x} ${s.y} Q ${mx} ${my} ${tg.x} ${tg.y}`);
        }
        for (const { g, n } of this.nodeEls) {
            g.setAttribute('transform', `translate(${n.x} ${n.y})`);
            const visible = this.activeGroups.has(n.model.group);
            g.style.display = visible ? '' : 'none';
        }
    }

    loop() {
        this.sim.tick();
        this.paint();
        this.raf = requestAnimationFrame(() => this.loop());
    }

    // Finding 1: loop() reschedules forever even while the canvas is hidden
    // (Datatypes tab), painting an invisible SVG at ~60fps. wireViews() calls
    // pause()/resume() when the canvas is hidden/shown.
    pause() {
        if (this.raf) { cancelAnimationFrame(this.raf); this.raf = null; }
    }

    resume() {
        // Reduced-motion mode never starts a loop (see mount()); don't start one here.
        if (!this.raf && !this.reduce) this.loop();
    }

    highlight(id, on) {
        const neighbors = new Set([id]);
        (this.data.relations || []).forEach((r) => {
            if (r.source === id) neighbors.add(r.target);
            if (r.target === id) neighbors.add(r.source);
        });
        this.nodeEls.forEach(({ g, n }) => g.classList.toggle('is-dim', on && !neighbors.has(n.id)));
        this.edgeEls.forEach(({ p, l }) => {
            const inc = l.source.id === id || l.target.id === id;
            p.classList.toggle('is-active', on && inc);
            p.classList.toggle('is-dim', on && !inc);
        });
    }

    wireDrag() {
        let dragging = null;
        let downX = 0;
        let downY = 0;
        const MOVE_THRESHOLD = 4; // px — below this, treat the gesture as a click, not a drag
        const toSvg = (evt) => {
            const r = this.svg.getBoundingClientRect();
            return { x: ((evt.clientX - r.left) / r.width) * this.w, y: ((evt.clientY - r.top) / r.height) * this.h };
        };
        this.nodeEls.forEach(({ g, n }) => {
            g.addEventListener('pointerdown', (e) => {
                dragging = n; g.setPointerCapture(e.pointerId);
                downX = e.clientX; downY = e.clientY;
                n._dragMoved = false;
                this.sim.reheat(0.9);
            });
            g.addEventListener('pointermove', (e) => {
                if (dragging !== n) return;
                if (!n._dragMoved && Math.hypot(e.clientX - downX, e.clientY - downY) > MOVE_THRESHOLD) {
                    n._dragMoved = true;
                }
                const p = toSvg(e);
                this.sim.setFixed(n.id, p.x, p.y);
                n.x = p.x; n.y = p.y;
                if (this.reduce) this.paint();
            });
            const end = () => { if (dragging === n) { this.sim.releaseFixed(n.id); dragging = null; } };
            g.addEventListener('pointerup', end);
            g.addEventListener('pointercancel', end);
        });
    }

    setActiveGroups(set) { this.activeGroups = set; this.paint(); }
    focus(modelId, trigger) {
        const hit = this.nodeEls.find(({ n }) => n.id === modelId);
        if (hit) { openDrawer(hit.n.model, this.data, trigger); this.highlight(modelId, true); setTimeout(() => this.highlight(modelId, false), 1200); }
    }
    destroy() {
        if (this.raf) cancelAnimationFrame(this.raf);
        if (this.resizeHandler) window.removeEventListener('resize', this.resizeHandler);
    }
}

function openDrawer(model, data, trigger) {
    const drawer = el('ms-ge-drawer');
    const body = el('ms-ge-drawer-body');
    const groups = data.groups || [];
    const group = groups.find((g) => g.id === model.group);
    const gcolor = groupColor(groups, model.group);
    const glabel = groupLabel(data, group) || model.group;

    // SECURITY: model.name/description/cidoc, ng.name, nd.name/datatype/cidoc are
    // DB-authored (graph designer content) rendered on an anonymous public page —
    // every one of them is escaped before entering the innerHTML string below.
    const fieldsHtml = (model.nodegroups || []).map((ng) => `
        <div class="ms-ge-ng">
            <h5>${esc(ng.name) || '—'}</h5>
            ${ng.nodes.map((nd) => `
                <div class="ms-ge-field">
                    <span class="ms-ge-dt" style="--c:${esc(datatypeColor(data.datatypes, nd.datatype))}">${esc(nd.datatype)}</span>
                    <span class="ms-ge-field-name">${esc(nd.name)}</span>
                    ${nd.cidoc ? `<span class="ms-ge-field-cidoc">${esc(nd.cidoc)}</span>` : ''}
                    ${nd.required ? `<span class="ms-ge-badge">${esc(t('msGeRequired', 'required'))}</span>` : ''}
                </div>`).join('')}
        </div>`).join('');

    const rels = (data.relations || []).filter((r) => r.source === model.id || r.target === model.id);
    const nameById = new Map((data.models || []).map((m) => [m.id, m.name]));
    const relHtml = rels.length ? rels.map((r) => {
        const other = r.source === model.id ? r.target : r.source;
        const dir = r.source === model.id ? '→' : '←';
        const otherName = nameById.get(other) || other;
        // r.count/r.fields record how many distinct fields on the model produced
        // this typed relationship — surfaced as a badge + tooltip when > 1.
        const countBadge =
            r.count > 1
                ? `<span class="ms-ge-rel-count" title="${esc((r.fields || []).join(', '))}">${esc(r.count)}</span>`
                : '';
        // r.label is the originating field's human name (e.g. "Related work"),
        // distinct from r.property (the prettified CIDOC-CRM property) — surfaced
        // as a native tooltip on the whole row.
        return `<button class="ms-ge-rel" data-focus="${esc(other)}" title="${esc(r.label)}">${dir} ${esc(otherName)} <em>${esc(r.property)}</em>${countBadge}</button>`;
    }).join('') : `<p class="text-muted">${esc(t('msGeNoRelations', 'No relations'))}</p>`;

    body.innerHTML = `
        <div class="ms-ge-drawer-head">
            <span class="ms-ge-drawer-group" style="background:${esc(gcolor)}">${esc(glabel)}</span>
            <h3>${esc(model.name)}</h3>
            <div class="ms-ge-drawer-meta">
                ${model.cidoc ? `<span class="ms-ge-chip">${esc(model.cidoc)}</span>` : ''}
                <span class="ms-ge-chip">${model.instances} ${esc(t('msGeRecords', 'records'))}</span>
                <span class="ms-ge-chip">${model.counts.nodegroups} ${esc(t('msGeNodegroups', 'field groups'))}</span>
            </div>
            ${model.description ? `<p class="ms-ge-drawer-desc">${esc(model.description)}</p>` : ''}
        </div>
        <div class="ms-ge-tabs">
            <button class="ms-ge-tab is-active" data-tab="fields">${esc(t('msGeFields', 'Fields'))}</button>
            <button class="ms-ge-tab" data-tab="relations">${esc(t('msGeRelations', 'Relations'))}</button>
        </div>
        <div class="ms-ge-tabpane" data-pane="fields">${fieldsHtml}</div>
        <div class="ms-ge-tabpane" data-pane="relations" hidden>
            ${rels.length ? `<p class="ms-ge-rel-hint">${esc(t('msGeTargets', '→ target · ← source'))}</p>` : ''}
            ${relHtml}
        </div>`;

    body.querySelectorAll('.ms-ge-tab').forEach((tab) => tab.addEventListener('click', () => {
        body.querySelectorAll('.ms-ge-tab').forEach((x) => x.classList.toggle('is-active', x === tab));
        body.querySelectorAll('.ms-ge-tabpane').forEach((p) => { p.hidden = p.dataset.pane !== tab.dataset.tab; });
    }));
    body.querySelectorAll('.ms-ge-rel').forEach((b) => b.addEventListener('click', () => {
        if (currentGraph) currentGraph.focus(b.dataset.focus, b);
    }));

    // Finding 2: remember who opened the drawer so closeDrawer() can return focus.
    drawerTrigger = trigger || el('ms-ge-canvas');

    // Finding 10: [hidden] is display:none, so adding .open in the same tick as
    // unhiding leaves no box to transition from and the slide-in never plays.
    // Unhide first, then add .open (and move focus in) on the next frame.
    drawer.hidden = false;
    requestAnimationFrame(() => {
        drawer.classList.add('open');
        const closeBtn = el('ms-ge-drawer-close');
        if (closeBtn) closeBtn.focus();
    });
    history.replaceState(null, '', `#model=${model.id}`);
}

// Finding 2 + 10: single close path used by the close button, Esc, and (via
// closeDrawer) anywhere else — reverses openDrawer's animation and restores
// focus to whatever triggered the open.
function closeDrawer() {
    const drawer = el('ms-ge-drawer');
    if (!drawer || drawer.hidden) return;
    drawer.classList.remove('open');
    let finished = false;
    const finish = () => {
        if (finished) return;
        finished = true;
        drawer.removeEventListener('transitionend', onTransitionEnd);
        drawer.hidden = true;
    };
    const onTransitionEnd = (e) => { if (e.target === drawer) finish(); };
    drawer.addEventListener('transitionend', onTransitionEnd);
    setTimeout(finish, 320); // fallback in case transitionend doesn't fire (matches the 0.28s CSS transition)

    const back = drawerTrigger || el('ms-ge-canvas');
    drawerTrigger = null;
    if (back && typeof back.focus === 'function') back.focus();
}

// Finding 2: wire the Esc-to-close + close-button listeners exactly once,
// regardless of how many times openDrawer()/render() run.
function wireDrawerChrome() {
    if (drawerChromeWired) return;
    drawerChromeWired = true;
    const closeBtn = el('ms-ge-drawer-close');
    if (closeBtn) closeBtn.addEventListener('click', closeDrawer);
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeDrawer();
    });
}

function wireViews(data, graph) {
    const plotlyBox = el('ms-ge-plotly');
    const canvas = el('ms-ge-canvas');
    let plotted = false;
    document.querySelectorAll('.ms-ge-view').forEach((btn) => btn.addEventListener('click', async () => {
        document.querySelectorAll('.ms-ge-view').forEach((b) => {
            const on = b === btn;
            b.classList.toggle('is-active', on);
            b.setAttribute('aria-selected', String(on));
        });
        const datatypes = btn.dataset.view === 'datatypes';
        canvas.hidden = datatypes;
        plotlyBox.hidden = !datatypes;
        // Finding 1: don't let the RAF loop keep ticking/painting an invisible SVG
        // while the Datatypes tab is showing.
        if (datatypes) graph.pause(); else graph.resume();
        if (datatypes && !plotted) { plotted = true; await drawPlotly(data, plotlyBox); }
    }));

    wireDrawerChrome();
}

function wireSearch(data, graph) {
    const input = el('ms-ge-search');
    input.addEventListener('change', () => {
        const q = input.value.trim().toLowerCase();
        if (!q) return;
        const hit = (data.models || []).find((m) => m.name.toLowerCase().includes(q));
        if (hit) graph.focus(hit.id, input);
    });
    document.querySelectorAll('.ms-ge-filter').forEach((f) => f.addEventListener('click', () => {
        const on = f.classList.toggle('is-on');
        f.setAttribute('aria-pressed', String(on));
        const active = new Set(Array.from(document.querySelectorAll('.ms-ge-filter.is-on')).map((x) => x.dataset.group));
        graph.setActiveGroups(active);
    }));
}

async function drawPlotly(data, box) {
    const Plotly = (await import('plotly.js-dist')).default;
    const dts = data.datatypes || [];
    const bar = {
        type: 'bar',
        x: dts.map((d) => d.label),
        y: dts.map((d) => d.count),
        marker: { color: dts.map((d) => d.color) },
    };
    Plotly.newPlot(box, [bar], {
        title: { text: t('msGeDatatypeChartTitle', 'Fields by datatype') },
        margin: { t: 40, r: 10, b: 90, l: 40 },
        paper_bgcolor: 'transparent', plot_bgcolor: 'transparent',
        font: { family: 'Sora, sans-serif' },
    }, { displayModeBar: false, responsive: true });
}

document.addEventListener('DOMContentLoaded', boot);
