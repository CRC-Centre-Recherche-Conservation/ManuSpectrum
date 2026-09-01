import initMsNav from "utils/ms-nav";
import { t, tv } from "utils/i18n";
import revealOnScroll from "utils/reveal-on-scroll";
import { createForceGraph } from "utils/force-graph";
// The Structure view uses THIS, never createForceGraph — see the header comment
// on tree-layout.js for why a solved layout is mandatory there.
import { layoutTree, ROW_PITCH, columnX } from "utils/tree-layout";
import {
    groupColor,
    datatypeColor,
    instanceRadius,
    contrastSafeStroke,
    mixWhite,
} from "utils/model-graph-colors";

const SVGNS = "http://www.w3.org/2000/svg";
const el = (id) => document.getElementById(id);
const svgEl = (tag, attrs) => {
    const n = document.createElementNS(SVGNS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, v));
    return n;
};
// ---------------------------------------------------------------------------
// WAVE 3 — why this page is no longer a node-link diagram by default.
//
// Measured on the live payload: 12 models, 45 unique connected pairs out of 66
// possible = 68% density. Node-link layouts stay legible up to roughly 15-20%
// density; at 68% they are a hairball by construction, and no amount of force
// tuning fixes that. The previous mitigation set `anchor: 0.26` against
// `center: 0.004` — the group anchors were 65x stronger than the physics, so
// node position was decided almost entirely by the 4-way group attribute that
// the legend and the filter chips already state in words. The simulation was
// decorative.
//
// So: the adjacency MATRIX is now the primary relations view (12x12 = 144 cells,
// all legible at once, and 68% density reads as texture rather than as noise),
// and the node-link survives as an EGO NETWORK drill-down — one model plus its
// direct neighbours, which is 5-11 nodes at low density, exactly the regime
// where node-link genuinely outperforms a matrix.
// ---------------------------------------------------------------------------

// Ego-network force tuning. Neighbours get an explicit elliptical ring anchor
// (see EgoView.build), so the simulation only has to resolve overlaps — it is
// not being asked to discover a layout it cannot discover.
const MS_EGO_FORCE = {
    charge: -1500,
    linkDistance: 200,
    center: 0.003,
    collide: 40,
    anchor: 0.16,
    // WAVE 3 item 5: the shared default is `alphaFloor: 0.015`, i.e. the nodes
    // drift under the cursor forever. On a page people read for minutes that
    // makes every click a moving target. Let alpha decay to zero and stop the
    // rAF loop (see EgoView.loop); only a drag reheats it.
    alphaFloor: 0,
};
const SETTLE_ALPHA = 0.006; // stop painting below this
const SETTLE_MS = 3000; // hard cap, even if alpha decays slowly
const EGO_PARALLEL_GAP = 26; // px between two parallel edges on the same pair
const LABEL_PAD = 14; // collision padding that keeps node labels off each other

// Datatypes that produce a resource-to-resource link. Drives the drawer's
// "relation fields only" toggle.
const RELATION_DATATYPES = new Set([
    "resource-instance",
    "resource-instance-list",
]);

// SECURITY: every value that originates from the /api/model-graph payload is
// DB-authored (graph/field names, CIDOC classes, descriptions, nodegroup names,
// group colors/labels). It reaches an anonymous public page, so it MUST be
// escaped before going into innerHTML — otherwise a graph designer can plant
// stored XSS. Values written via textContent (SVG labels, figcaption) or via the
// DOM setAttribute API (SVG node/edge attributes) are already safe and are not
// re-escaped below.
const esc = (v) =>
    String(v ?? "").replace(
        /[&<>"']/g,
        (c) =>
            ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;",
            })[c],
    );

// Plotly renders tick/hover strings through its own pseudo-HTML parser, which
// honours a subset of tags (<a>, <b>, <span style>) — so a payload string is an
// injection surface there even though it never touches innerHTML. Strip anything
// tag-shaped before handing a DB value to Plotly.
const plain = (v) => String(v ?? "").replace(/[<>]/g, "");

// Groups carry both label_en/label_fr from the payload; pick the one matching
// the page's active language (data.language, set server-side from the request).
function groupLabel(data, group) {
    if (!group) return "";
    const preferred = data.language === "fr" ? group.label_fr : group.label_en;
    return preferred || group.label_en || group.label_fr || group.id || "";
}

// ---------------------------------------------------------------------------
// Shared state + derived index
// ---------------------------------------------------------------------------

const state = {
    data: null,
    index: null,
    reduce: false,
    view: "matrix",
    matrixSort: "group",
    tableSort: { key: "links", dir: -1 },
    tableMode: "models", // 'models' | 'fields' — the Fields mode flattens the trees
    fieldSort: { key: "model", dir: 1 },
    activeGroups: new Set(),
    query: "",
    selectedId: null,
};

// Module-scoped (not on `window`) so nothing leaks to the global object.
let ego = null;
let structure = null;
let drawerTrigger = null;
let drawerChromeWired = false;

const cellKey = (a, b) => `${a}\u0000${b}`;

function buildIndex(data) {
    const models = (data.models || []).slice();
    const relations = data.relations || [];
    const byId = new Map(models.map((m) => [m.id, m]));
    const degree = new Map(models.map((m) => [m.id, 0]));
    const neighbours = new Map(models.map((m) => [m.id, new Set()]));
    const cells = new Map(); // "src\0tgt" -> relation[]

    relations.forEach((r) => {
        if (!byId.has(r.source) || !byId.has(r.target)) return;
        degree.set(r.source, degree.get(r.source) + 1);
        degree.set(r.target, degree.get(r.target) + 1);
        if (r.source !== r.target) {
            neighbours.get(r.source).add(r.target);
            neighbours.get(r.target).add(r.source);
        }
        const k = cellKey(r.source, r.target);
        if (!cells.has(k)) cells.set(k, []);
        cells.get(k).push(r);
    });

    return { models, relations, byId, degree, neighbours, cells };
}

// Row/column ordering for the matrix (and the default ordering everywhere else).
function orderModels(sort) {
    const { models, degree } = state.index;
    const list = models.slice();
    if (sort === "alpha")
        return list.sort((a, b) => a.name.localeCompare(b.name));
    if (sort === "degree") {
        return list.sort(
            (a, b) =>
                (degree.get(b.id) || 0) - (degree.get(a.id) || 0) ||
                a.name.localeCompare(b.name),
        );
    }
    // "group" — follow the payload's own group order, so the four families read
    // as contiguous blocks and the block structure of the matrix is the message.
    const gi = new Map((state.data.groups || []).map((g, i) => [g.id, i]));
    return list.sort(
        (a, b) =>
            (gi.has(a.group) ? gi.get(a.group) : 99) -
                (gi.has(b.group) ? gi.get(b.group) : 99) ||
            a.name.localeCompare(b.name),
    );
}

const visibleModels = (sort) =>
    orderModels(sort).filter((m) => state.activeGroups.has(m.group));

const matchesQuery = (m) =>
    !state.query || m.name.toLowerCase().includes(state.query);

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

async function boot() {
    initMsNav();
    revealOnScroll();

    // Onboarding panel: open by default (server-rendered); remember the
    // visitor's choice so it stays collapsed on return visits. localStorage
    // can throw (private browsing) — in that case it simply stays open.
    const howto = el("ms-ge-howto");
    if (howto) {
        try {
            if (localStorage.getItem("ms-ge-howto") === "closed")
                howto.open = false;
            howto.addEventListener("toggle", () => {
                localStorage.setItem(
                    "ms-ge-howto",
                    howto.open ? "open" : "closed",
                );
            });
        } catch {
            /* stay open */
        }
    }

    const stage = el("ms-ge-stage");
    if (!stage) return;
    const reduce = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
    ).matches;

    try {
        const res = await fetch(stage.dataset.api, {
            headers: { Accept: "application/json" },
        });
        if (!res.ok) throw new Error(res.status);
        const data = await res.json();
        el("ms-ge-loading").hidden = true;
        render(data, reduce);
    } catch {
        el("ms-ge-loading").hidden = true;
        el("ms-ge-error").hidden = false;
    }
}

function render(data, reduce) {
    state.data = data;
    state.index = buildIndex(data);
    state.reduce = reduce;
    state.activeGroups = new Set((data.groups || []).map((g) => g.id));

    renderStats(data);
    renderLead(data);
    renderLegend(data);
    renderFilters(data);

    ego = new EgoView(data, state.index, reduce);
    ego.mount();

    structure = new StructureView(data, state.index, reduce);
    structure.mount();

    renderMatrix();
    renderTable();

    wireViews(data);
    wireSorts();
    wireSearch();
    wireTableModes();
    wireDrawerChrome();
    openFromHash(data);
}

// The hero lead quotes live figures. The template ships today's values so the
// sentence is already correct without JS; this replaces them with the payload's.
function renderLead(data) {
    const box = el("ms-ge-lead");
    const s = data.stats || {};
    if (!box || s.nodes === undefined) return;
    box.textContent = tv(
        "msGeLead",
        "Every field in ManuSpectrum and every link between models: {fields} fields across {models} models, {pct}% of them bound to a published thesaurus rather than free text. Click any model to read its schema.",
        { fields: s.nodes, models: s.models, pct: s.thesaurus_pct },
    );
}

const hashParam = (name) => {
    // Every caller passes a literal today, but escape regex metacharacters
    // anyway — hashParam('node.id') must match a literal dot, not "any char".
    const safe = String(name).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const m = new RegExp(`[#&]${safe}=([^&]+)`).exec(location.hash || "");
    return m ? decodeURIComponent(m[1]) : null;
};

// `#model=<id>` (written since WAVE 3) now grows optional `view`/`root`/`node`
// segments, so a researcher can link a colleague straight to "the way we model a
// joining event" rather than to the page and a set of instructions.
function updateHash() {
    const parts = [];
    // Write the slug when the model has one: #model=document is citable in a
    // paper; #model=<uuid> is not. openFromHash accepts both.
    const modelRef = (mid) => {
        const m =
            mid && state.index && state.index.byId && state.index.byId.get(mid);
        return (m && m.slug) || mid;
    };
    if (state.selectedId)
        parts.push(`model=${encodeURIComponent(modelRef(state.selectedId))}`);
    if (state.view === "structure" && structure && structure.modelId) {
        if (!state.selectedId)
            parts.push(
                `model=${encodeURIComponent(modelRef(structure.modelId))}`,
            );
        parts.push("view=structure");
        if (structure.rootId && structure.rootId !== structure.modelRoot) {
            parts.push(`root=${encodeURIComponent(structure.rootId)}`);
        }
        if (structure.activeNodeId)
            parts.push(`node=${encodeURIComponent(structure.activeNodeId)}`);
    }
    if (parts.length) {
        history.replaceState(null, "", `#${parts.join("&")}`);
    } else if (location.hash) {
        // Nothing selected any more (drawer closed, back to the matrix):
        // clear the stale deep link instead of leaving an outdated #model=…
        // for the reader to copy and share.
        history.replaceState(null, "", location.pathname + location.search);
    }
}

function openFromHash(data) {
    const id = hashParam("model");
    if (!id) return;
    // Accept both forms: #model=document (the citable slug the page now
    // writes) and #model=<uuid> (links shared before slugs existed).
    const model = (data.models || []).find((m) => m.id === id || m.slug === id);
    if (!model) return;
    const view = hashParam("view");
    if (view === "structure" && structure) {
        structure.setModel(model.id, { root: hashParam("root") });
        showView("structure");
        const node = hashParam("node");
        if (node && structure.byId.has(node)) {
            structure
                .ancestors(node)
                .forEach((a) => structure.expanded.add(a.id));
            structure.activeNodeId = node;
            structure.draw();
            openNodeInspector(structure, structure.byId.get(node));
            structure.flash(node);
        }
        return;
    }
    ego.setFocus(model.id);
    openDrawer(model, data);
}

// ---------------------------------------------------------------------------
// Header furniture
// ---------------------------------------------------------------------------

function renderStats(data) {
    const s = data.stats || {};
    const items = [
        [s.models, t("msGeModels", "models")],
        [s.relations, t("msGeStatRelations", "relations")],
        [s.nodes, t("msGeStatFields", "fields")],
        [s.datatypes, t("msGeStatDatatypes", "datatypes")],
    ];
    // item 9: a <dl> of value/label pairs — no aria-live, because nothing here
    // changes after load and an unprompted announcement of four bare numbers is
    // noise, not information.
    el("ms-ge-stats").innerHTML = items
        .map(
            ([v, l]) =>
                `<div class="ms-ge-stat"><dt>${esc(l)}</dt><dd>${v === undefined || v === null ? "—" : esc(v)}</dd></div>`,
        )
        .join("");
    renderVolume(data);
}

// WAVE 4c — state the real data volume up front.
// Four of the twelve models hold nothing yet. A researcher finds that out by
// clicking into an empty drawer, and an unannounced discovery costs far more
// trust than a stated one. Both numbers are summed from the payload rather than
// written into the template, so they cannot go stale the way the "84
// relationships" figure did.
function renderVolume(data) {
    const box = el("ms-ge-volume");
    if (!box) return;
    const models = data.models || [];
    const records = models.reduce((n, m) => n + (Number(m.instances) || 0), 0);
    const empty = models.filter((m) => !Number(m.instances)).length;
    const parts = [
        tv("msGeVolumeRecords", "{n} records published", { n: records }),
    ];
    if (empty) {
        parts.push(
            tv("msGeVolumeOpen", "{n} models defined and open for deposit", {
                n: empty,
            }),
        );
    }
    // Freshness marker — the payload is cached, so say when it was built.
    if (data.generated_at) {
        const when = new Date(data.generated_at);
        if (!Number.isNaN(when.getTime())) {
            const lang = document.documentElement.lang || "en";
            parts.push(
                tv("msGeGeneratedAt", "data as of {date}", {
                    date: when.toLocaleDateString(lang),
                }),
            );
        }
    }
    box.textContent = parts.join(" · ");
}

function renderLegend(data) {
    const groups = (data.groups || []).filter((g) =>
        (data.models || []).some((m) => m.group === g.id),
    );
    const swatches = groups
        .map(
            (g) =>
                `<li><i class="ms-ge-legend-swatch" style="background:${esc(mixWhite(g.color, 22))};border-color:${esc(contrastSafeStroke(g.color))}"></i>${esc(groupLabel(data, g))}</li>`,
        )
        .join("");
    // item 3: the size channel now carries `instances`, so it needs legending —
    // an unlegended size channel is just decoration with extra steps.
    const sizeKeys = `
        <li class="ms-ge-legend-size"><i class="ms-ge-legend-dot is-small"></i><i class="ms-ge-legend-dot is-large"></i>${esc(t("msGeSizeLegend", "Circle size = published records"))}</li>
        <li class="ms-ge-legend-size"><i class="ms-ge-legend-dot is-empty"></i>${esc(t("msGeEmptyLegend", "Dashed outline = no records published yet"))}</li>`;
    el("ms-ge-legend").innerHTML = swatches + sizeKeys;
}

function renderFilters(data) {
    el("ms-ge-filters").innerHTML = (data.groups || [])
        .filter((g) => (data.models || []).some((m) => m.group === g.id))
        .map(
            (g) =>
                `<button class="ms-ge-filter is-on" data-group="${esc(g.id)}" style="--c:${esc(g.color)}" aria-pressed="true">${esc(groupLabel(data, g))}</button>`,
        )
        .join("");
}

// ---------------------------------------------------------------------------
// item 1 — the adjacency matrix (primary view)
// ---------------------------------------------------------------------------

// Tint ramp for a cell, indexed by how many distinct typed relations it holds
// (measured max on the live payload: 4). Rendering the hue as a tint behind ink
// text — rather than as a saturated fill behind white — is what keeps the cell
// digit readable at every level, the same inversion WAVE 2 applied to the chips.
const CELL_TINT = [0, 20, 38, 58, 78];
const tintFor = (n) => CELL_TINT[Math.min(n, CELL_TINT.length - 1)];

function relationSummary(rels) {
    return rels
        .map((r) => r.property)
        .filter(Boolean)
        .join(" · ");
}

function countLabel(n) {
    return n === 1
        ? t("msGeRelation1", "1 relation")
        : tv("msGeRelationN", "{n} relations", { n });
}

function renderMatrix() {
    const box = el("ms-ge-matrix");
    if (!box) return;
    const data = state.data;
    const order = visibleModels(state.matrixSort);
    const { cells } = state.index;

    if (!order.length) {
        box.innerHTML = `<p class="text-muted ms-ge-empty">${esc(t("msGeNoGroups", "No family selected — turn one back on to see the matrix."))}</p>`;
        return;
    }

    const groups = data.groups || [];
    const groupOf = new Map(groups.map((g) => [g.id, g]));
    const showBands = state.matrixSort === "group";

    // Contiguous runs of the same family, used both for the banded header row
    // and for the heavier rule drawn at each family boundary.
    const runs = [];
    order.forEach((m, i) => {
        const last = runs[runs.length - 1];
        if (last && last.group === m.group) last.len += 1;
        else runs.push({ group: m.group, len: 1, start: i });
    });
    const boundaries = new Set(runs.map((r) => r.start));

    const caption = tv(
        "msGeMatrixCaption",
        "Adjacency matrix: {models} models, {relations} typed relationships. Rows are sources, columns are targets.",
        {
            models: order.length,
            relations: state.index.relations.length,
        },
    );

    let head = "";
    if (showBands) {
        head += `<tr class="ms-ge-mx-bandrow"><td class="ms-ge-mx-corner"></td>${runs
            .map((run) => {
                const g = groupOf.get(run.group);
                const c = groupColor(groups, run.group);
                return `<th class="ms-ge-mx-band" scope="colgroup" colspan="${run.len}" style="--c:${esc(contrastSafeStroke(c))}"><span>${esc(groupLabel(data, g) || run.group)}</span></th>`;
            })
            .join("")}</tr>`;
    }
    head += `<tr><td class="ms-ge-mx-corner"><span class="ms-ge-sr">${esc(t("msGeMatrixCorner", "Source model, down; target model, across"))}</span></td>${order
        .map((m, i) => {
            const c = groupColor(groups, m.group);
            return `<th scope="col" class="ms-ge-mx-colh${boundaries.has(i) ? " is-boundary" : ""}" data-id="${esc(m.id)}" data-col="${i}" style="--c:${esc(contrastSafeStroke(c))}"><button type="button" class="ms-ge-mx-headbtn" data-id="${esc(m.id)}"><span>${esc(m.name)}</span></button></th>`;
        })
        .join("")}</tr>`;

    const body = order
        .map((src, r) => {
            const c = groupColor(groups, src.group);
            const rowCells = order
                .map((tgt, col) => {
                    const base = `data-row="${r}" data-col="${col}" role="gridcell" tabindex="-1"`;
                    const boundary = boundaries.has(col) ? " is-boundary" : "";
                    if (src.id === tgt.id) {
                        return `<td class="ms-ge-mx-cell is-self${boundary}" ${base} aria-label="${esc(t("msGeSameModel", "same model"))}"></td>`;
                    }
                    const rels = cells.get(cellKey(src.id, tgt.id)) || [];
                    if (!rels.length) {
                        return `<td class="ms-ge-mx-cell is-empty${boundary}" ${base} aria-label="${esc(`${src.name} → ${tgt.name}: ${t("msGeNoRelation", "no relation")}`)}"></td>`;
                    }
                    const n = rels.length;
                    const summary = relationSummary(rels);
                    const label = `${src.name} → ${tgt.name}: ${countLabel(n)}${summary ? ` — ${summary}` : ""}`;
                    return `<td class="ms-ge-mx-cell is-on${boundary}" ${base} data-src="${esc(src.id)}" data-tgt="${esc(tgt.id)}" aria-label="${esc(label)}" style="--c:${esc(mixWhite(c, tintFor(n)))};--b:${esc(contrastSafeStroke(c))}"><span class="ms-ge-mx-n">${esc(n)}</span></td>`;
                })
                .join("");
            return `<tr data-id="${esc(src.id)}"${boundaries.has(r) ? ' class="is-boundary"' : ""}><th scope="row" class="ms-ge-mx-rowh" data-id="${esc(src.id)}" style="--c:${esc(contrastSafeStroke(c))}"><button type="button" class="ms-ge-mx-headbtn" data-id="${esc(src.id)}">${esc(src.name)}</button></th>${rowCells}</tr>`;
        })
        .join("");

    box.innerHTML = `
        <div class="ms-ge-matrix-scroll">
            <table class="ms-ge-mx" role="grid">
                <caption class="ms-ge-sr">${esc(caption)}</caption>
                <thead>${head}</thead>
                <tbody>${body}</tbody>
            </table>
        </div>
        <p class="ms-ge-mx-info" id="ms-ge-mx-info">${esc(t("msGeMatrixHint", "Point at or focus a cell to read its CIDOC-CRM properties. Select one to open the model."))}</p>`;

    wireMatrix(order);
    applyQueryToMatrix();
    markSelection();
}

function wireMatrix(order) {
    const table = document.querySelector(".ms-ge-mx");
    const info = el("ms-ge-mx-info");
    if (!table) return;
    const cols = order.length;
    const cellAt = (r, c) =>
        table.querySelector(`.ms-ge-mx-cell[data-row="${r}"][data-col="${c}"]`);

    // Roving tabindex: the grid is one tab stop, arrow keys move inside it.
    // 144 individually tabbable cells would bury the rest of the page.
    let cursor = { r: 0, c: 0 };
    const first = cellAt(0, 0);
    if (first) first.tabIndex = 0;
    const moveTo = (r, c) => {
        const next = cellAt(r, c);
        if (!next) return;
        const prev = cellAt(cursor.r, cursor.c);
        if (prev) prev.tabIndex = -1;
        cursor = { r, c };
        next.tabIndex = 0;
        next.focus();
    };

    const describe = (cell) => {
        if (!info) return;
        // aria-label already carries the same sentence, so this is set as text —
        // no escaping needed and no double announcement for screen readers.
        info.textContent =
            cell && cell.getAttribute("aria-label")
                ? cell.getAttribute("aria-label")
                : t(
                      "msGeMatrixHint",
                      "Point at or focus a cell to read its CIDOC-CRM properties. Select one to open the model.",
                  );
    };

    table.addEventListener("keydown", (e) => {
        const cell = e.target.closest && e.target.closest(".ms-ge-mx-cell");
        if (!cell) return;
        const r = Number(cell.dataset.row);
        const c = Number(cell.dataset.col);
        const keys = {
            ArrowRight: [r, Math.min(cols - 1, c + 1)],
            ArrowLeft: [r, Math.max(0, c - 1)],
            ArrowDown: [Math.min(cols - 1, r + 1), c],
            ArrowUp: [Math.max(0, r - 1), c],
            Home: [r, 0],
            End: [r, cols - 1],
        };
        if (keys[e.key]) {
            e.preventDefault();
            moveTo(keys[e.key][0], keys[e.key][1]);
            return;
        }
        if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
            e.preventDefault();
            activateCell(cell);
        }
    });

    table.addEventListener("focusin", (e) => {
        const cell = e.target.closest && e.target.closest(".ms-ge-mx-cell");
        if (cell) describe(cell);
    });
    table.addEventListener("mouseover", (e) => {
        const cell = e.target.closest && e.target.closest(".ms-ge-mx-cell");
        if (cell) describe(cell);
    });
    table.addEventListener("mouseleave", () => describe(null));
    table.addEventListener("click", (e) => {
        const head = e.target.closest && e.target.closest(".ms-ge-mx-headbtn");
        if (head) {
            const model = state.index.byId.get(head.dataset.id);
            if (model) {
                ego.setFocus(model.id);
                openDrawer(model, state.data, head);
            }
            return;
        }
        const cell = e.target.closest && e.target.closest(".ms-ge-mx-cell");
        if (cell) activateCell(cell);
    });
}

function activateCell(cell) {
    if (!cell.dataset.src) return;
    const model = state.index.byId.get(cell.dataset.src);
    if (!model) return;
    ego.setFocus(model.id);
    openDrawer(model, state.data, cell, cell.dataset.tgt);
}

function applyQueryToMatrix() {
    const table = document.querySelector(".ms-ge-mx");
    if (!table) return;
    const dimIds = new Set(
        state.index.models.filter((m) => !matchesQuery(m)).map((m) => m.id),
    );
    const on = Boolean(state.query);
    table.classList.toggle("is-searching", on);
    table.querySelectorAll(".ms-ge-mx-rowh, .ms-ge-mx-colh").forEach((h) => {
        h.classList.toggle("is-dim", on && dimIds.has(h.dataset.id));
    });
    table.querySelectorAll("tbody tr").forEach((tr) => {
        const rowDim = on && dimIds.has(tr.dataset.id);
        tr.querySelectorAll(".ms-ge-mx-cell").forEach((cell) => {
            const colDim =
                on && cell.dataset.tgt ? dimIds.has(cell.dataset.tgt) : false;
            cell.classList.toggle("is-dim", rowDim || colDim);
        });
    });
}

// ---------------------------------------------------------------------------
// item 2 — the ego network (drill-down)
// ---------------------------------------------------------------------------

const pNumber = (property) => {
    const m = /\bP\d+[a-z]?/i.exec(String(property || ""));
    return m ? m[0] : "";
};

class EgoView {
    constructor(data, index, reduce) {
        this.data = data;
        this.index = index;
        this.reduce = reduce;
        this.svg = el("ms-ge-svg");
        this.figcap = el("ms-ge-figcap");
        this.focusId = null;
        this.raf = null;
        this.settled = false;
        this.nodeEls = [];
        this.edgeEls = [];
    }

    mount() {
        this.measure();
        // Default the drill-down to the most connected model, so the view is
        // never empty and lands on the one that best demonstrates why an ego
        // network is the right form here.
        const byDegree = this.index.models
            .slice()
            .sort(
                (a, b) =>
                    (this.index.degree.get(b.id) || 0) -
                    (this.index.degree.get(a.id) || 0),
            );
        this.focusId = byDegree.length ? byDegree[0].id : null;
        this.build();
        this.wireResize();
    }

    measure() {
        const rect = this.svg.getBoundingClientRect();
        this.w = rect.width || 900;
        this.h = rect.height || 560;
        this.svg.setAttribute("viewBox", `0 0 ${this.w} ${this.h}`);
    }

    // Re-measure and re-anchor, but only if the box actually changed size. The
    // drawer now takes a 380px grid column out of the stage (item 6), so opening
    // or closing it genuinely resizes the canvas and the ring anchors have to
    // move with it — while a no-op call (e.g. switching back to a tab that is
    // already the right size) must NOT throw away a settled layout.
    reflow() {
        const prevW = this.w;
        const prevH = this.h;
        this.measure();
        if (Math.abs(this.w - prevW) > 2 || Math.abs(this.h - prevH) > 2)
            this.build();
    }

    setFocus(id) {
        // Guarded: the live search calls this on every keystroke once it is down
        // to a single hit, and rebuilding an unchanged graph would throw away the
        // settled layout (and any in-flight drag) for nothing.
        if (!this.index.byId.has(id) || this.focusId === id) return;
        this.focusId = id;
        this.build();
    }

    // The set actually drawn: the focus model plus the neighbours that survive
    // the family filters. item 4 — hidden nodes are excluded from the SIMULATION
    // too, not merely from the paint, so they stop shoving the visible layout
    // around for reasons nobody can see.
    visibleSet() {
        const focus = this.index.byId.get(this.focusId);
        if (!focus) return { focus: null, nodes: [], links: [] };
        const neighbourIds = Array.from(
            this.index.neighbours.get(focus.id) || [],
        )
            .map((id) => this.index.byId.get(id))
            .filter((m) => m && state.activeGroups.has(m.group))
            .sort((a, b) => a.name.localeCompare(b.name));
        const shown = new Set([focus.id, ...neighbourIds.map((m) => m.id)]);
        const links = this.index.relations.filter(
            (r) =>
                (r.source === focus.id || r.target === focus.id) &&
                shown.has(r.source) &&
                shown.has(r.target),
        );
        return { focus, neighbours: neighbourIds, links };
    }

    build() {
        this.pause();
        const { focus, neighbours, links } = this.visibleSet();
        if (!focus) {
            this.svg.innerHTML = "";
            this.nodeEls = [];
            this.edgeEls = [];
            this.figcap.textContent = t(
                "msGeEgoEmpty",
                "Select a model to see it with its directly connected models.",
            );
            return;
        }

        // item 11 — the old layout filled 32% of the stage (a 518x308 span in a
        // 900x560 box). Anchoring the neighbours on an ELLIPTICAL ring sized from
        // the live rect uses the whole canvas by construction, instead of hoping
        // the physics wanders out there.
        const k = Math.min(1, this.w / 900);
        const models = [focus, ...neighbours];
        const radii = new Map(
            models.map((m) => [m.id, instanceRadius(m.instances) * k]),
        );
        const maxR = Math.max(...radii.values());
        const cx = this.w / 2;
        const cy = this.h / 2;
        const rx = Math.max(80, this.w / 2 - maxR - 46);
        const ry = Math.max(70, this.h / 2 - maxR - 34);

        const nodes = models.map((m, i) => {
            const isEgo = i === 0;
            const vr = radii.get(m.id);
            const a = neighbours.length
                ? -Math.PI / 2 + ((i - 1) / neighbours.length) * Math.PI * 2
                : 0;
            const ax = isEgo ? cx : cx + Math.cos(a) * rx;
            const ay = isEgo ? cy : cy + Math.sin(a) * ry;
            return {
                id: m.id,
                model: m,
                isEgo,
                vr,
                // item 12 — labels sit at vr + 16 with a 12px font, so collision has
                // to account for the label box, not just the disc. Padded here AND
                // given a white halo in pages.scss; either alone still collides.
                r: vr + LABEL_PAD,
                x: ax,
                y: ay,
                ax,
                ay,
            };
        });

        this.sim = createForceGraph({
            nodes,
            links: links.map((r) => ({ source: r.source, target: r.target })),
            width: this.w,
            height: this.h,
            options: {
                ...MS_EGO_FORCE,
                linkDistance: Math.min(rx, ry) * 1.1,
                charge: MS_EGO_FORCE.charge * k,
                anchor: MS_EGO_FORCE.anchor,
            },
        });
        const simById = new Map(this.sim.nodes.map((n) => [n.id, n]));

        this.buildDom(
            this.sim.nodes,
            links.map((rel) => ({
                rel,
                source: simById.get(rel.source),
                target: simById.get(rel.target),
            })),
        );

        this.figcap.textContent = tv(
            "msGeEgoCaption",
            "{model} and its {n} directly connected models, joined by {r} typed relationships. Each curve is one relationship, labelled with its CIDOC-CRM property.",
            { model: focus.name, n: neighbours.length, r: links.length },
        );

        this.settled = false;
        this.settleUntil =
            (typeof performance !== "undefined"
                ? performance.now()
                : Date.now()) + SETTLE_MS;
        if (this.reduce) {
            for (let i = 0; i < 320; i++) this.sim.tick();
            this.paint();
            this.settled = true;
        } else if (state.view === "network") {
            this.loop();
        } else {
            // Pre-settle off-screen so switching to the tab lands on a finished
            // layout rather than on an animation nobody asked to watch.
            for (let i = 0; i < 320; i++) this.sim.tick();
            this.paint();
            this.settled = true;
        }
        this.wireDrag();
        markSelection();
    }

    buildDom(nodes, links) {
        this.svg.innerHTML = "";
        const defs = svgEl("defs", {});
        this.gEdges = svgEl("g", { class: "ms-ge-edges" });
        this.gLabels = svgEl("g", { class: "ms-ge-edge-labels" });
        this.gNodes = svgEl("g", { class: "ms-ge-nodes" });
        this.svg.appendChild(defs);
        this.svg.appendChild(this.gEdges);
        this.svg.appendChild(this.gLabels);
        this.svg.appendChild(this.gNodes);

        // item 3 — every edge used to be `Q(mid, mid - 30)`, identical for both
        // directions and for every parallel edge on a pair, so they stacked
        // EXACTLY: 25 of the 70 relations had no pixels of their own. Fan them
        // out by index within the unordered pair, with the sign flipped for the
        // reverse direction so A→B and B→A never land on each other either.
        const fans = new Map();
        links.forEach((l) => {
            const key = [l.rel.source, l.rel.target]
                .slice()
                .sort()
                .join("\u0000");
            if (!fans.has(key)) fans.set(key, []);
            const bucket = fans.get(key);
            l._i = bucket.length;
            bucket.push(l);
            l._forward = l.rel.source === key.split("\u0000")[0];
        });
        links.forEach((l) => {
            const bucket = fans.get(
                [l.rel.source, l.rel.target].slice().sort().join("\u0000"),
            );
            l._n = bucket.length;
        });

        // Arrow markers, one per distinct stroke colour. The id is generated from
        // an index, never from payload text, so nothing DB-authored reaches it.
        const strokes = new Map();
        const markerFor = (color) => {
            if (strokes.has(color)) return strokes.get(color);
            const id = `ms-ge-arrow-${strokes.size}`;
            const marker = svgEl("marker", {
                id,
                viewBox: "0 0 10 10",
                refX: "9",
                refY: "5",
                markerWidth: "6",
                markerHeight: "6",
                orient: "auto-start-reverse",
            });
            const path = svgEl("path", {
                d: "M 0 0 L 10 5 L 0 10 z",
                fill: color,
            });
            marker.appendChild(path);
            defs.appendChild(marker);
            strokes.set(color, id);
            return id;
        };

        this.edgeEls = links.map((l) => {
            // item 3 — edge colour now encodes the SOURCE family (the old
            // rgba(ink,.18) measured 1.54:1, below the 3:1 floor for graphical
            // objects), darkened by contrastSafeStroke until it clears 3:1 on the
            // white stage; edge width encodes r.count.
            const raw = groupColor(
                this.data.groups,
                (this.index.byId.get(l.rel.source) || {}).group,
            );
            const color = contrastSafeStroke(raw);
            const p = svgEl("path", {
                class: "ms-ge-edge",
                fill: "none",
                stroke: color,
                "stroke-width": String(1.5 + (Number(l.rel.count) || 1) * 0.9),
                "marker-end": `url(#${markerFor(color)})`,
            });
            const title = svgEl("title", {});
            title.textContent = l.rel.property || "";
            p.appendChild(title);
            this.gEdges.appendChild(p);

            // item 3 — the CIDOC property was reachable only through a native
            // <title>, i.e. after a hover delay and never by keyboard. The
            // P-number is now drawn permanently on the curve, and pointing at the
            // edge promotes it to the full property name.
            const label = svgEl("text", {
                class: "ms-ge-edge-label",
                "text-anchor": "middle",
            });
            label.textContent = pNumber(l.rel.property);
            this.gLabels.appendChild(label);

            const entry = { p, label, l };
            const show = (on) => {
                label.textContent = on
                    ? l.rel.property || pNumber(l.rel.property)
                    : pNumber(l.rel.property);
                label.classList.toggle("is-full", on);
                p.classList.toggle("is-active", on);
            };
            p.addEventListener("mouseenter", () => show(true));
            p.addEventListener("mouseleave", () => show(false));
            return entry;
        });

        this.nodeEls = nodes.map((n) => {
            const g = svgEl("g", {
                class: `ms-ge-node${n.isEgo ? " is-ego" : ""}`,
                "data-id": n.id,
                tabindex: "0",
                role: "button",
                // aria-label goes through setAttribute (SVGNS DOM API), not
                // innerHTML — already safe, no esc() needed.
                "aria-label": `${n.model.name} — ${n.model.instances} ${t("msGeRecords", "records")}`,
            });
            const raw = groupColor(this.data.groups, n.model.group);
            const empty = !Number(n.model.instances);
            // item 3 — "no records yet" is a categorical fact, not a small
            // number, so it gets its own mark (hollow, dashed) instead of just
            // being the smallest circle.
            const c = svgEl("circle", {
                r: n.vr,
                class: empty ? "ms-ge-disc is-empty" : "ms-ge-disc",
                fill: empty ? "#ffffff" : mixWhite(raw, 68),
                stroke: contrastSafeStroke(raw),
            });
            const label = svgEl("text", {
                class: "ms-ge-node-label",
                "text-anchor": "middle",
                dy: n.vr + 16,
            });
            label.textContent = n.model.name;
            g.appendChild(c);
            g.appendChild(label);

            // wireDrag() calls setPointerCapture, so the synthesized click after a
            // drag is redirected here regardless of pointer travel. n._dragMoved
            // records whether this click followed a real drag; if so, swallow it.
            g.addEventListener("click", () => {
                if (n._dragMoved) {
                    n._dragMoved = false;
                    return;
                }
                this.activate(n, g);
            });
            g.addEventListener("keydown", (e) => {
                if (
                    e.key === "Enter" ||
                    e.key === " " ||
                    e.key === "Spacebar"
                ) {
                    e.preventDefault();
                    this.activate(n, g);
                }
            });
            // item 5 — hovering means the user is aiming at something, so stop
            // the drift immediately rather than 3s from now.
            g.addEventListener("mouseenter", () => {
                this.settle();
                this.highlight(n.id, true);
            });
            g.addEventListener("mouseleave", () => this.highlight(n.id, false));
            g.addEventListener("focus", () => this.settle());
            this.gNodes.appendChild(g);
            return { g, c, n };
        });
    }

    activate(n, g) {
        // Clicking a neighbour re-centres the drill-down on it; clicking the ego
        // just opens its details.
        if (!n.isEgo) {
            openDrawer(n.model, this.data, el("ms-ge-canvas"));
            this.setFocus(n.id);
        } else {
            openDrawer(n.model, this.data, g);
        }
    }

    wireResize() {
        // mount() bakes this.w/this.h into the viewBox once; toSvg() (in wireDrag)
        // scales a live getBoundingClientRect() against those values, so drag
        // coordinates desync after a window resize. Debounced re-measure + relayout.
        let timer = null;
        this.resizeHandler = () => {
            clearTimeout(timer);
            timer = setTimeout(() => this.reflow(), 150);
        };
        window.addEventListener("resize", this.resizeHandler);
    }

    paint() {
        const hidden = new Set();
        for (const { g, n } of this.nodeEls) {
            g.setAttribute("transform", `translate(${n.x} ${n.y})`);
            const visible = state.activeGroups.has(n.model.group);
            g.style.display = visible ? "" : "none";
            if (!visible) hidden.add(n.id);
        }
        for (const { p, label, l } of this.edgeEls) {
            const s = l.source;
            const tg = l.target;
            if (!s || !tg) continue;
            // item 4 — paint() used to set `display` on the nodes and NEVER on
            // this.edgeEls, so filtering a family left its edges hanging in empty
            // space. Endpoint visibility now drives the edge and its label too.
            const on = !hidden.has(s.id) && !hidden.has(tg.id);
            p.style.display = on ? "" : "none";
            label.style.display = on ? "" : "none";
            if (!on) continue;

            const dx = tg.x - s.x;
            const dy = tg.y - s.y;
            const len = Math.hypot(dx, dy) || 1;
            const off =
                (l._i - (l._n - 1) / 2) *
                EGO_PARALLEL_GAP *
                (l._forward ? 1 : -1);
            const nx = (-dy / len) * off * 2;
            const ny = (dx / len) * off * 2;
            const mx = (s.x + tg.x) / 2 + nx;
            const my = (s.y + tg.y) / 2 + ny;
            // Stop the curve at the target's rim so the arrowhead is not buried
            // under the disc.
            const ex = tg.x - (dx / len) * (tg.vr + 8);
            const ey = tg.y - (dy / len) * (tg.vr + 8);
            p.setAttribute("d", `M ${s.x} ${s.y} Q ${mx} ${my} ${ex} ${ey}`);
            label.setAttribute("x", String((s.x + 2 * mx + ex) / 4));
            label.setAttribute("y", String((s.y + 2 * my + ey) / 4));
        }
    }

    loop() {
        this.sim.tick();
        this.paint();
        const now =
            typeof performance !== "undefined" ? performance.now() : Date.now();
        if (this.sim.alpha() <= SETTLE_ALPHA || now >= this.settleUntil) {
            this.raf = null;
            this.settled = true;
            return;
        }
        this.raf = requestAnimationFrame(() => this.loop());
    }

    settle() {
        if (this.raf) cancelAnimationFrame(this.raf);
        this.raf = null;
        this.settled = true;
    }

    // loop() must not reschedule while the canvas is hidden (Datatypes/Table/
    // Matrix tabs), or it paints an invisible SVG at ~60fps. wireViews() calls
    // pause()/resume() as the network pane is hidden/shown.
    pause() {
        if (this.raf) cancelAnimationFrame(this.raf);
        this.raf = null;
    }

    resume() {
        if (!this.raf && !this.reduce && !this.settled) this.loop();
    }

    reheat(v) {
        this.settled = false;
        this.settleUntil =
            (typeof performance !== "undefined"
                ? performance.now()
                : Date.now()) + 2000;
        this.sim.reheat(v);
        if (!this.raf && !this.reduce) this.loop();
    }

    highlight(id, on) {
        this.nodeEls.forEach(({ g, n }) =>
            g.classList.toggle(
                "is-dim",
                on && n.id !== id && !this.isLinked(id, n.id),
            ),
        );
        this.edgeEls.forEach(({ p, label, l }) => {
            const inc = l.rel.source === id || l.rel.target === id;
            p.classList.toggle("is-active", on && inc);
            p.classList.toggle("is-dim", on && !inc);
            label.classList.toggle("is-dim", on && !inc);
        });
    }

    isLinked(a, b) {
        const set = this.index.neighbours.get(a);
        return Boolean(set && set.has(b));
    }

    wireDrag() {
        let dragging = null;
        let downX = 0;
        let downY = 0;
        const MOVE_THRESHOLD = 4; // px — below this the gesture is a click, not a drag
        const toSvg = (evt) => {
            const r = this.svg.getBoundingClientRect();
            return {
                x: ((evt.clientX - r.left) / r.width) * this.w,
                y: ((evt.clientY - r.top) / r.height) * this.h,
            };
        };
        this.nodeEls.forEach(({ g, n }) => {
            g.addEventListener("pointerdown", (e) => {
                dragging = n;
                g.setPointerCapture(e.pointerId);
                downX = e.clientX;
                downY = e.clientY;
                n._dragMoved = false;
            });
            g.addEventListener("pointermove", (e) => {
                if (dragging !== n) return;
                if (
                    !n._dragMoved &&
                    Math.hypot(e.clientX - downX, e.clientY - downY) >
                        MOVE_THRESHOLD
                ) {
                    n._dragMoved = true;
                    // item 5 — a drag is the ONLY thing that reheats the layout now.
                    this.reheat(0.7);
                }
                const p = toSvg(e);
                this.sim.setFixed(n.id, p.x, p.y);
                n.x = p.x;
                n.y = p.y;
                if (this.reduce || this.settled) this.paint();
            });
            const end = () => {
                if (dragging === n) {
                    this.sim.releaseFixed(n.id);
                    dragging = null;
                }
            };
            g.addEventListener("pointerup", end);
            g.addEventListener("pointercancel", end);
        });
    }

    applyQuery() {
        const on = Boolean(state.query);
        this.nodeEls.forEach(({ g, n }) =>
            g.classList.toggle("is-dim", on && !matchesQuery(n.model)),
        );
    }

    destroy() {
        this.pause();
        if (this.resizeHandler)
            window.removeEventListener("resize", this.resizeHandler);
    }
}

// ---------------------------------------------------------------------------
// The STRUCTURE view — one model drawn as the tree it actually is.
//
// WHY THIS IS NOT force-graph.js, and must never become it:
// every one of the 12 models is a STRICT TREE — `edges == nodes - 1`, exactly one
// root, zero cycles, zero cross-links (verified against the live DB, all 12).
// A force simulation exists to *discover* unknown structure; here the structure is
// known exactly, so physics would re-derive it badly and, worse, NON-
// DETERMINISTICALLY — a different picture on every page load. This is a public
// reference page that researchers screenshot and cite, so a layout that cannot be
// reproduced is disqualifying. The pass below is a solved O(n) layered layout:
// same input, same pixels, every time. No rAF loop, no settling, no reheat.
//
// force-graph.js stays exactly as it is and remains correct for the ego network,
// which is a genuinely dense (68%) 12-node graph with no hierarchy to exploit.
// ---------------------------------------------------------------------------

// The vertical run of every elbow lives in the empty strip at the right-hand end
// of the PARENT's column, GUTTER px before the child column starts. It used to
// leave from `parent.x + LABEL_GAP` — i.e. exactly where the parent's own label
// text begins — so a branch whose subtree is vertically centred on it (y2 === y1)
// degenerated into one horizontal line drawn the full width of that label, and
// rendered it struck through. Departing from the gutter makes the crossing
// geometrically impossible instead of merely unlikely.
const GUTTER = 26;
const LEAF_R = 7;
const NG_R = 8;
const LABEL_GAP = 14;
// Frame padding added to the measured content box (see sizeFrame).
const FRAME_PAD_X = 28;
const FRAME_PAD_Y = 24;
// Advance-width estimates for the three type ramps used in the SVG. They only
// have to be a FLOOR for the frame: getBBox() refines the real number wherever
// it is available, and the taper/label geometry is unaffected by them.
const EM_LABEL = 6.6; // .ms-ge-st-label      12px sans
const EM_ROOT = 7.6; // .ms-ge-st-rootlabel  12.5px sans 600
const EM_MONO = 6.0; // .ms-ge-st-cidoc      10px mono
const EM_BADGE = 5.7; // .ms-ge-st-badge      9.5px mono
// P2 has type (124x) and P1 is identified by (91x) are ~40% of all edges and carry
// almost no discriminating information. Dimming them is what lets P98i was born /
// P132 spatiotemporally overlaps with actually stand out. The legend says so.
const DIM_PROPS = new Set(["P1", "P2"]);
// At or below this many nodes the whole tree opens at once (Project 28, Place 31
// is the borderline case); above it, only the root + its level-1 groups.
const AUTO_EXPAND_MAX = 30;
const SVG_BREAKPOINT = 768; // below this the SVG is not drawn and the outline IS the view

// Width of the column a node at `depth` occupies, derived from tree-layout's own
// ramp rather than hardcoded, so the taper (210 → 130) stays the single source of
// truth for both the layout and the edges drawn over it.
const colWidth = (depth) => columnX(depth + 1) - columnX(depth);

// Right-hand edge of a row's own NAME mark — the root's capsule, or the label
// text plus its required glyph. An edge must not depart to the left of this, or
// it is drawn through the very label it belongs to.
function labelEnd(row) {
    const name = String((row.node || {}).name || "");
    if (row.depth === 0)
        return row.x - 10 + Math.max(90, name.length * EM_ROOT + 26);
    return (
        row.x +
        LABEL_GAP +
        name.length * EM_LABEL +
        (row.node.required ? 10 : 0)
    );
}

// Right-hand edge of everything a row draws (label, CIDOC line, badge, target
// capsules). nodeMark records the real number as it appends; the fallback is the
// bare disc, so a row that was never drawn cannot widen the frame.
const contentRight = (row) =>
    Number.isFinite(row.right) ? row.right : row.x + NG_R;

// "1 fields" is wrong in both languages. gettext plurals are not available on the
// JS side (arches.translations is a flat string map), so the singular forms are
// separate keys and chosen here.
function fieldCount(d) {
    if (d.groups) {
        return d.groups === 1
            ? tv("msGeStructGroupOne", "{n} fields · {m} group", {
                  n: d.fields,
                  m: d.groups,
              })
            : tv("msGeStructFieldsGroups", "{n} fields · {m} groups", {
                  n: d.fields,
                  m: d.groups,
              });
    }
    return d.fields === 1
        ? tv("msGeStructFieldOne", "{n} field", { n: d.fields })
        : tv("msGeStructFields", "{n} fields", { n: d.fields });
}

class StructureView {
    constructor(data, index, reduce) {
        this.data = data;
        this.index = index;
        this.reduce = reduce;
        this.svg = el("ms-ge-struct-svg");
        this.scroll = el("ms-ge-struct-scroll");
        this.outlineBox = el("ms-ge-struct-outline");
        this.figcap = el("ms-ge-struct-figcap");
        this.crumbs = el("ms-ge-struct-crumbs");
        this.modelId = null;
        this.rootId = null;
        this.backModelId = null;
        // Initialised empty rather than left undefined: the sub-toolbar exists in
        // the DOM from first paint (merely `hidden`), so its handlers are reachable
        // — via a programmatic click, an extension, or a deep link naming a model
        // that is not in the payload — before any model has been prepared.
        this.byId = new Map();
        this.children = new Map();
        this._desc = new Map();
        this.expanded = new Set();
        this.query = "";
        this.showSemantic = true;
        this.showAllCidoc = false;
        this.outlineOpen = false;
        this.activeNodeId = null;
        this.rows = [];
        this.mounted = false;
    }

    // -- data prep ----------------------------------------------------------

    prepare() {
        const model = this.index.byId.get(this.modelId);
        const st = (model && model.structure) || { root: null, nodes: [] };
        this.model = model;
        this.byId = new Map((st.nodes || []).map((n) => [n.id, n]));
        this.children = new Map();
        this.byId.forEach((_v, id) => this.children.set(id, []));
        (st.nodes || []).forEach((n) => {
            if (n.parent && this.children.has(n.parent))
                this.children.get(n.parent).push(n);
        });
        // Stable ordering: children sorted by name, so the drawing is reproducible.
        this.children.forEach((list) =>
            list.sort((a, b) => a.name.localeCompare(b.name)),
        );
        this.modelRoot = st.root;
        this._desc = new Map();
    }

    // A "structural node" is a pure semantic branch: it groups nothing the user
    // fills in and is not a field group either. Only ~21 exist across all 12
    // models — but they carry the CIDOC path, so they are shown BY DEFAULT.
    isStructural(n) {
        return (
            n.datatype === "semantic" &&
            !n.is_collector &&
            n.id !== this.modelRoot
        );
    }

    // Children as drawn. With structural nodes hidden, a branch is spliced out and
    // its property is folded into the path of whatever it was hiding, so
    // `Birth --P4--> Time-Span --P82a--> date` still reads as `P4·P82a`.
    kids(node) {
        const out = [];
        const walk = (list, via) => {
            list.forEach((c) => {
                const step = c.property_code
                    ? via.concat(c.property_code)
                    : via;
                if (!this.showSemantic && this.isStructural(c)) {
                    walk(this.children.get(c.id) || [], step);
                } else {
                    out.push({ node: c, via: step });
                }
            });
        };
        walk(this.children.get(node.id) || [], []);
        return out;
    }

    // {fields, groups} beneath a node — drives the collapsed badge, so a closed
    // disc still says how much it is hiding.
    descendants(id) {
        if (this._desc.has(id)) return this._desc.get(id);
        let fields = 0;
        let groups = 0;
        (this.children.get(id) || []).forEach((c) => {
            if (c.datatype !== "semantic") fields += 1;
            if (c.is_collector) groups += 1;
            const sub = this.descendants(c.id);
            fields += sub.fields;
            groups += sub.groups;
        });
        const out = { fields, groups };
        this._desc.set(id, out);
        return out;
    }

    // Search hits the four things this audience actually types: a field name, a
    // datatype, a CIDOC class ("E4 Period") and a property code ("P132").
    matches(n) {
        if (!this.query) return true;
        return [n.name, n.datatype, n.cidoc, n.property, n.property_code].some(
            (v) =>
                String(v ?? "")
                    .toLowerCase()
                    .includes(this.query),
        );
    }

    hitCount() {
        let n = 0;
        this.byId.forEach((v) => {
            if (v.id !== this.modelRoot && this.matches(v)) n += 1;
        });
        return n;
    }

    ancestors(id) {
        const out = [];
        let cur = this.byId.get(id);
        while (cur && cur.parent && this.byId.has(cur.parent)) {
            cur = this.byId.get(cur.parent);
            out.unshift(cur);
        }
        return out;
    }

    // -- expansion ----------------------------------------------------------

    defaultExpansion() {
        this.expanded = new Set();
        if (!this.rootId) return;
        if (this.byId.size <= AUTO_EXPAND_MAX) {
            this.byId.forEach((_v, id) => this.expanded.add(id));
        } else {
            // Root + its level-1 groups: Person becomes 10 discs instead of 83,
            // which is already a truer account of the model than the flat list of
            // 23 "nodegroups" the drawer shows today.
            this.expanded.add(this.rootId);
        }
    }

    expandAll() {
        if (!this.modelId) return;
        this.byId.forEach((_v, id) => this.expanded.add(id));
        this.draw();
    }

    collapseAll() {
        if (!this.modelId) return;
        this.expanded = new Set([this.rootId]);
        this.draw();
    }

    autoExpandForQuery() {
        if (!this.query) return;
        this.byId.forEach((n) => {
            if (!this.matches(n)) return;
            this.ancestors(n.id).forEach((a) => this.expanded.add(a.id));
        });
    }

    // -- public entry points ------------------------------------------------

    setModel(id, opts) {
        const o = opts || {};
        if (!this.index.byId.has(id)) return;
        if (o.from && o.from !== id) this.backModelId = o.from;
        else if (!o.keepBack) this.backModelId = null;
        this.modelId = id;
        this.prepare();
        this.rootId = o.root && this.byId.has(o.root) ? o.root : this.modelRoot;
        this.defaultExpansion();
        if (o.root && this.byId.has(o.root)) this.expanded.add(o.root);
        this.activeNodeId = null;
        this.draw();
    }

    reroot(id) {
        if (!this.byId.has(id)) return;
        this.rootId = id;
        this.expanded.add(id);
        this.draw();
        updateHash();
    }

    mount() {
        const select = el("ms-ge-struct-model");
        if (select) {
            // textContent on <option> — no innerHTML, so payload names are safe here.
            select.replaceChildren(
                ...orderModels("alpha").map((m) => {
                    const o = document.createElement("option");
                    o.value = m.id;
                    o.textContent = m.name;
                    return o;
                }),
            );
            select.addEventListener("change", () => {
                this.setModel(select.value);
                updateHash();
            });
        }
        this.wireTools();
        this.wirePan();
        this.renderLegend();
        this.mounted = true;
    }

    ensureModel() {
        if (this.modelId && this.index.byId.has(this.modelId)) return;
        // Default to the most connected model, same rule as the ego view.
        const byDegree = this.index.models
            .slice()
            .sort(
                (a, b) =>
                    (this.index.degree.get(b.id) || 0) -
                    (this.index.degree.get(a.id) || 0),
            );
        if (byDegree.length) this.setModel(byDegree[0].id);
    }

    syncSelect() {
        const select = el("ms-ge-struct-model");
        if (select && this.modelId) select.value = this.modelId;
    }

    // -- layout (the deterministic pass) ------------------------------------

    layout() {
        return layoutTree(
            this.byId.get(this.rootId),
            (node) => this.kids(node),
            (node) => this.expanded.has(node.id),
        );
    }

    // -- draw ---------------------------------------------------------------

    draw() {
        if (!this.modelId) return;
        this.syncSelect();
        this.autoExpandForQuery();
        const { rows, slots } = this.layout();
        this.rows = rows;
        this.renderCrumbs();
        this.renderSvg(rows, slots);
        this.renderOutline();
        this.renderCaption();
        this.renderQueryCount();
    }

    wide() {
        return typeof window.matchMedia === "function"
            ? window.matchMedia(`(min-width: ${SVG_BREAKPOINT}px)`).matches
            : true;
    }

    renderSvg(rows, slots) {
        const svg = this.svg;
        if (!svg) return;
        svg.replaceChildren();
        // Below 768px the SVG is not rendered at all: depth 7 x tapered columns
        // cannot be made legible at 375px, and pretending otherwise produces a
        // pinch-zoom puzzle. The outline below is the real view there.
        if (!this.wide()) {
            svg.setAttribute("width", "0");
            svg.setAttribute("height", "0");
            return;
        }
        const gEdges = svgEl("g", { class: "ms-ge-st-edges" });
        const gNodes = svgEl("g", { class: "ms-ge-st-nodes" });
        svg.appendChild(gEdges);
        svg.appendChild(gNodes);

        const groups = this.data.groups || [];
        const family = groupColor(groups, (this.model || {}).group);
        const byRow = new Map(rows.map((r) => [r.node.id, r]));
        const pad = 20;

        rows.forEach((row) => {
            const n = row.node;
            const parentRow = n.parent ? byRow.get(n.parent) : null;
            // With structural nodes hidden the drawn parent may be an ancestor, so
            // fall back to the nearest ancestor that is actually on screen.
            let anchor = parentRow;
            if (!anchor && n.parent) {
                const chain = this.ancestors(n.id).slice().reverse();
                anchor =
                    chain.map((a) => byRow.get(a.id)).find(Boolean) || null;
            }
            if (anchor && row.depth > 0) {
                const y1 = anchor.y + pad;
                const x2 = row.x;
                const y2 = row.y + pad;
                // The vertical run goes in the gutter at the end of the parent's
                // column, but never inside the child's outermost ring; and where a
                // long parent label overruns the gutter it is pushed further right
                // still, so the run clears the text it used to be drawn through.
                const bend = Math.min(
                    Math.max(
                        anchor.x + colWidth(anchor.depth) - GUTTER,
                        labelEnd(anchor) + 6,
                    ),
                    x2 - NG_R - 12,
                );
                // Depart just past the parent's label, so the horizontal segment is
                // the stub between label and gutter rather than the label itself.
                const x1 = Math.min(labelEnd(anchor) + 6, bend);
                const path = svgEl("path", {
                    class: "ms-ge-st-edge",
                    fill: "none",
                    d: `M ${x1} ${y1} H ${bend} V ${y2} H ${x2 - LEAF_R - 3}`,
                });
                const title = svgEl("title", {});
                title.textContent =
                    row.via.length > 1 ? row.via.join(" · ") : n.property || "";
                path.appendChild(title);
                gEdges.appendChild(path);

                const code = row.via.length
                    ? row.via.join("·")
                    : n.property_code;
                if (code) {
                    // End-anchored just LEFT of the vertical run. Anchoring it
                    // against the child's disc instead (x2 - NG_R - 10) made the
                    // chip grow leftwards straight across the vertical connector,
                    // so every code sat on the line. Ending it before the bend
                    // keeps chips in a clean column in the gutter, and start-
                    // anchoring at the bend is no better — codes longer than three
                    // glyphs then ran out over the disc they label.
                    const chip = svgEl("text", {
                        class: `ms-ge-st-prop${DIM_PROPS.has(code) ? " is-common" : ""}`,
                        x: String(bend - 5),
                        y: String(y2 - 4),
                        "text-anchor": "end",
                    });
                    chip.textContent = code; // textContent — payload-safe
                    const ct = svgEl("title", {});
                    ct.textContent =
                        row.via.length > 1
                            ? row.via.join(" · ")
                            : n.property || "";
                    chip.appendChild(ct);
                    gEdges.appendChild(chip);
                }
            }

            gNodes.appendChild(this.nodeMark(row, family, pad));
        });

        this.sizeFrame(svg, rows, slots, pad);
    }

    // Size the frame from what was actually DRAWN. The old `maxX + 320` was a
    // guess at "label + CIDOC line + badges + target capsule", and a long name
    // carrying a `→ Target` capsule overran it, so the SVG was narrower than its
    // own content and the capsule was truncated at the right edge.
    //
    // getBBox() is the exact answer, but it is a layout call: jsdom does not
    // implement it, and an SVG in a `hidden` pane reports an empty box. So the
    // analytic extent — computed from the same metrics the marks were placed
    // with — is kept as a floor, and the measurement only ever widens it. Both
    // terms are pure functions of the payload, so the frame stays reproducible.
    sizeFrame(svg, rows, slots, pad) {
        let w =
            rows.reduce((m, r) => Math.max(m, contentRight(r)), 0) +
            FRAME_PAD_X;
        let h = Math.max(slots, 1) * ROW_PITCH + pad + FRAME_PAD_Y;

        if (typeof svg.getBBox === "function") {
            let box;
            try {
                box = svg.getBBox();
            } catch {
                box = null; // detached or display:none — keep the analytic floor
            }
            if (box && Number.isFinite(box.width) && box.width > 0) {
                w = Math.max(w, box.x + box.width + FRAME_PAD_X);
                h = Math.max(h, box.y + box.height + FRAME_PAD_Y);
            }
        }

        w = Math.ceil(w);
        h = Math.ceil(h);
        svg.setAttribute("width", String(w));
        svg.setAttribute("height", String(h));
        svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
    }

    nodeMark(row, family, pad) {
        const n = row.node;
        const isRoot = row.depth === 0;
        const g = svgEl("g", {
            class: `ms-ge-st-node${isRoot ? " is-root" : ""}${row.expandable ? " is-branch" : ""}${
                this.query && !this.matches(n) ? " is-dim" : ""
            }${this.query && this.matches(n) ? " is-hit" : ""}${
                n.id === this.activeNodeId ? " is-active" : ""
            }`,
            transform: `translate(${row.x} ${row.y + pad})`,
            "data-id": n.id,
            tabindex: "-1",
        });

        // Running right-hand extent of this row, in absolute coordinates. sizeFrame
        // uses it as the floor for the SVG width so nothing can be clipped.
        let right = row.x + NG_R;

        if (isRoot) {
            // The model root is a capsule, not a disc — it is a different KIND of
            // thing from a field. Tint + 2px family border + ink text: a solid
            // family fill behind white measured 3.68:1 and fails 4.5:1.
            const label = String(n.name || "");
            const wCap = Math.max(90, label.length * EM_ROOT + 26);
            right = Math.max(right, row.x - 10 + wCap);
            g.appendChild(
                svgEl("rect", {
                    class: "ms-ge-st-capsule",
                    x: "-10",
                    y: "-13",
                    rx: "13",
                    width: String(wCap),
                    height: "26",
                    fill: mixWhite(family, 12),
                    stroke: contrastSafeStroke(family),
                }),
            );
            const txt = svgEl("text", {
                class: "ms-ge-st-rootlabel",
                x: "4",
                y: "4",
            });
            txt.textContent = label;
            g.appendChild(txt);
        } else {
            const isNg = Boolean(n.is_collector);
            const r = isNg ? NG_R : LEAF_R;
            // Ring COUNT is a shape channel, so it survives colour blindness and
            // greyscale printing: no ring = plain field, one ring = a field group,
            // two rings = a repeatable field group.
            if (isNg) {
                if (n.cardinality === "n") {
                    g.appendChild(
                        svgEl("circle", {
                            class: "ms-ge-st-ring",
                            r: String(r + 3),
                        }),
                    );
                    g.appendChild(
                        svgEl("circle", {
                            class: "ms-ge-st-ring",
                            r: String(r + 6),
                        }),
                    );
                } else {
                    g.appendChild(
                        svgEl("circle", {
                            class: "ms-ge-st-ring",
                            r: String(r + 3),
                        }),
                    );
                }
            }
            g.appendChild(
                svgEl("circle", {
                    class: "ms-ge-st-disc",
                    r: String(r),
                    fill: datatypeColor(this.data.datatypes, n.datatype),
                }),
            );

            const label = svgEl("text", {
                class: `ms-ge-st-label${n.required ? " is-required" : ""}`,
                x: String(LABEL_GAP),
                y: "4",
            });
            label.textContent = String(n.name || "");
            if (n.required) {
                // Required is weight + glyph, never colour alone.
                const star = svgEl("tspan", { class: "ms-ge-st-req" });
                star.textContent = " ∗";
                label.appendChild(star);
            }
            g.appendChild(label);
            right = Math.max(right, labelEnd(row));

            // CIDOC class as a second line: on by default only where it is the
            // modelling (groups, structural branches). On leaves it is almost
            // always Literal / E41 / E55 — noise that would triple the ink.
            const showCidoc =
                this.showAllCidoc || n.is_collector || this.isStructural(n);
            if (showCidoc && n.cidoc) {
                const sub = svgEl("text", {
                    class: "ms-ge-st-cidoc",
                    x: String(LABEL_GAP),
                    y: "15",
                });
                sub.textContent = n.cidoc;
                g.appendChild(sub);
                right = Math.max(
                    right,
                    row.x + LABEL_GAP + String(n.cidoc).length * EM_MONO,
                );
            }

            // Everything after the label is laid out from ONE running cursor.
            // It starts at the label's true end — labelEnd() includes the required
            // "∗", which the badge and the capsules used to omit, so a required
            // node's badge sat on top of its own star. And because the badge and
            // the first capsule were previously fixed offsets only 8px apart, any
            // node carrying both drew them over each other ("Instrument 1 →
            // Instrument"). Advancing a cursor makes both impossible by construction.
            let cursor = labelEnd(row) - row.x + 16;

            // Collapsed branches say how much they are hiding.
            if (row.expandable && !row.open) {
                const d = this.descendants(n.id);
                const badge = svgEl("text", {
                    class: "ms-ge-st-badge",
                    x: String(cursor),
                    y: "4",
                });
                badge.textContent = fieldCount(d);
                g.appendChild(badge);
                const bw = badge.textContent.length * EM_BADGE;
                right = Math.max(right, row.x + cursor + bw);
                cursor += bw + 12;
            }

            // The money feature: an outbound relation shows the model it points at,
            // tinted in THAT model's family colour, and clicking jumps there.
            this.targetModels(n).forEach((tm) => {
                const tw = Math.max(58, String(tm.name).length * 6.4 + 20);
                const tx = cursor;
                cursor += tw + 8;
                right = Math.max(right, row.x + tx + tw);
                const tg = svgEl("g", {
                    class: "ms-ge-st-target",
                    "data-target": tm.id,
                    transform: `translate(${tx} 0)`,
                    tabindex: "-1",
                    role: "button",
                    "aria-label": tv("msGeStructViewModel", "View {model} →", {
                        model: tm.name,
                    }),
                });
                const tc = groupColor(this.data.groups, tm.group);
                tg.appendChild(
                    svgEl("rect", {
                        class: "ms-ge-st-target-cap",
                        x: "0",
                        y: "-9",
                        rx: "9",
                        width: String(tw),
                        height: "18",
                        fill: mixWhite(tc, 14),
                        stroke: contrastSafeStroke(tc),
                    }),
                );
                const tt = svgEl("text", {
                    class: "ms-ge-st-target-label",
                    x: "9",
                    y: "4",
                });
                tt.textContent = `→ ${tm.name}`;
                tg.appendChild(tt);
                g.appendChild(tg);
            });
        }

        row.right = right;

        g.addEventListener("click", (e) => {
            const cap =
                e.target.closest && e.target.closest(".ms-ge-st-target");
            if (cap) {
                e.stopPropagation();
                this.jumpToModel(cap.dataset.target);
                return;
            }
            if (this._panned) return; // swallow the click that ends a pan
            if (row.expandable && !this.query) this.toggle(n.id);
            this.select(n.id);
        });
        g.addEventListener("dblclick", (e) => {
            e.preventDefault();
            if (row.expandable) this.reroot(n.id);
        });
        return g;
    }

    targetModels(n) {
        const ids = ((n.config || {}).target_graphs || []).filter((id) =>
            this.index.byId.has(id),
        );
        return ids.map((id) => this.index.byId.get(id));
    }

    jumpToModel(id) {
        if (!this.index.byId.has(id)) return;
        this.setModel(id, { from: this.modelId });
        updateHash();
    }

    toggle(id) {
        if (this.expanded.has(id)) this.expanded.delete(id);
        else this.expanded.add(id);
        this.draw();
    }

    select(id) {
        const n = this.byId.get(id);
        if (!n) return;
        this.activeNodeId = id;
        openNodeInspector(this, n);
        this.markActive();
        updateHash();
    }

    markActive() {
        if (this.svg) {
            this.svg.querySelectorAll(".ms-ge-st-node").forEach((g) => {
                g.classList.toggle(
                    "is-active",
                    g.dataset.id === this.activeNodeId,
                );
            });
        }
        if (this.outlineBox) {
            this.outlineBox
                .querySelectorAll('[role="treeitem"]')
                .forEach((li) => {
                    li.classList.toggle(
                        "is-active",
                        li.dataset.id === this.activeNodeId,
                    );
                });
        }
    }

    // prefers-reduced-motion: no auto-pan, no tween — jump, then flash once.
    flash(id) {
        const target =
            (this.svg &&
                this.svg.querySelector(
                    `.ms-ge-st-node[data-id="${CSS.escape(id)}"]`,
                )) ||
            null;
        if (!target) return;
        target.classList.add("is-flash");
        setTimeout(() => target.classList.remove("is-flash"), 400);
    }

    // -- chrome -------------------------------------------------------------

    // Deepest level BELOW the current root, whether or not it is expanded — the
    // caption describes the model, not the current expansion state.
    subtreeDepth() {
        const rootNode = this.byId.get(this.rootId);
        if (!rootNode) return 0;
        let max = 0;
        const walk = (id, d) => {
            max = Math.max(max, d);
            (this.children.get(id) || []).forEach((c) => walk(c.id, d + 1));
        };
        walk(this.rootId, 0);
        return max;
    }

    renderCaption() {
        if (!this.figcap) return;
        const rootNode = this.byId.get(this.rootId);
        if (!rootNode) return;
        // The subtree may be collapsed, so quote its real totals rather than
        // whatever happens to be on screen.
        const sub = this.descendants(this.rootId);
        this.figcap.textContent = tv(
            "msGeStructCaption",
            "{model}: {n} fields in {g} field groups, nested {d} levels deep.",
            {
                model: rootNode.name,
                n: sub.fields,
                g: sub.groups,
                d: this.subtreeDepth(),
            },
        );
    }

    renderCrumbs() {
        if (!this.crumbs) return;
        const rootNode = this.byId.get(this.rootId);
        const chain = rootNode
            ? this.ancestors(this.rootId).concat(rootNode)
            : [];
        const back = this.backModelId
            ? this.index.byId.get(this.backModelId)
            : null;
        // SECURITY: model + node names are DB-authored; esc() on every one.
        const backChip = back
            ? `<button type="button" class="ms-ge-struct-back" data-back="${esc(back.id)}">${esc(
                  tv("msGeStructBack", "← {model}", { model: back.name }),
              )}</button>`
            : "";
        const items = chain
            .map((n, i) => {
                const last = i === chain.length - 1;
                return `<button type="button" class="ms-ge-struct-crumb${
                    last ? " is-current" : ""
                }" data-root="${esc(n.id)}"${last ? ' aria-current="true"' : ""}>${esc(
                    n.name,
                )}</button>`;
            })
            .join('<span class="ms-ge-struct-sep" aria-hidden="true">›</span>');
        const note =
            rootNode && rootNode.id !== this.modelRoot
                ? `<span class="ms-ge-struct-note">${esc(
                      tv("msGeStructReroot", "Showing {node} and below", {
                          node: rootNode.name,
                      }),
                  )}</span>`
                : "";
        this.crumbs.innerHTML = backChip + items + note;
        this.crumbs
            .querySelectorAll(".ms-ge-struct-crumb")
            .forEach((b) =>
                b.addEventListener("click", () => this.reroot(b.dataset.root)),
            );
        const backBtn = this.crumbs.querySelector(".ms-ge-struct-back");
        if (backBtn) {
            backBtn.addEventListener("click", () => {
                this.setModel(backBtn.dataset.back);
                updateHash();
            });
        }
    }

    renderQueryCount() {
        const box = el("ms-ge-struct-qcount");
        if (!box) return;
        if (!this.query) {
            box.textContent = "";
            box.classList.remove("is-none");
            return;
        }
        const hits = this.hitCount();
        const total = Math.max(0, this.byId.size - 1);
        box.textContent = hits
            ? tv("msGeStructCount", "{n} of {total} fields", { n: hits, total })
            : tv(
                  "msGeStructNomatch",
                  "No field, class or property matches “{q}”.",
                  {
                      q: this.query,
                  },
              );
        box.classList.toggle("is-none", !hits);
    }

    renderLegend() {
        const box = el("ms-ge-struct-legend");
        if (!box) return;
        box.innerHTML = [
            `<li>${esc(t("msGeStructLegendGroup", "Ring = field group · double ring = repeatable"))}</li>`,
            `<li>${esc(t("msGeStructLegendRequired", "∗ = required"))}</li>`,
            // Risk 6: dimmed P1/P2 could read as "disabled" — say what it means.
            `<li class="ms-ge-struct-legend-dim">${esc(t("msGeStructDimmed", "Common properties (P1, P2) are dimmed."))}</li>`,
        ].join("");
    }

    // -- the outline: same tree, real DOM, and the mobile rendering ----------

    renderOutline() {
        const box = this.outlineBox;
        if (!box) return;
        const rootNode = this.byId.get(this.rootId);
        if (!rootNode) {
            box.innerHTML = "";
            return;
        }
        const build = (node, via, level, posinset, setsize) => {
            const kidList = this.kids(node);
            const expandable = kidList.length > 0;
            const open = expandable && this.expanded.has(node.id);
            const dim = this.query && !this.matches(node);
            const code = via.length ? via.join("·") : node.property_code;
            const d = expandable && !open ? this.descendants(node.id) : null;
            // SECURITY: name / datatype / cidoc / property code all come from the
            // payload (graph-designer authored) and are esc()'d here.
            const meta = [
                code ? `<span class="ms-ge-out-prop">${esc(code)}</span>` : "",
                `<span class="ms-ge-out-dt">${esc(node.datatype)}</span>`,
                node.cidoc
                    ? `<span class="ms-ge-out-cidoc">${esc(node.cidoc)}</span>`
                    : "",
                node.required
                    ? `<span class="ms-ge-out-req">${esc(t("msGeStructRequired", "Required"))}</span>`
                    : "",
                node.is_collector && node.cardinality === "n"
                    ? `<span class="ms-ge-out-card">${esc(t("msGeStructCardN", "Repeatable"))}</span>`
                    : "",
                d
                    ? `<span class="ms-ge-out-count">${esc(
                          fieldCount(d),
                      )}</span>`
                    : "",
            ].join("");
            const kidsHtml = open
                ? `<ul role="group">${kidList
                      .map((k, i) =>
                          build(
                              k.node,
                              k.via,
                              level + 1,
                              i + 1,
                              kidList.length,
                          ),
                      )
                      .join("")}</ul>`
                : "";
            return `<li role="treeitem" data-id="${esc(node.id)}" aria-level="${level}" aria-setsize="${setsize}" aria-posinset="${posinset}"${
                expandable ? ` aria-expanded="${open}"` : ""
            } tabindex="-1" class="${dim ? "is-dim" : ""}${
                this.query && this.matches(node) ? " is-hit" : ""
            }"><span class="ms-ge-out-row"><span class="ms-ge-out-name">${esc(
                node.name,
            )}</span>${meta}</span>${kidsHtml}</li>`;
        };
        // The tree's accessible name is the same sentence as the <figcaption>, so
        // the SVG and the outline describe themselves identically.
        const sub = this.descendants(this.rootId);
        box.innerHTML = `<ul role="tree" class="ms-ge-out-tree" aria-label="${esc(
            tv(
                "msGeStructCaption",
                "{model}: {n} fields in {g} field groups, nested {d} levels deep.",
                {
                    model: rootNode.name,
                    n: sub.fields,
                    g: sub.groups,
                    d: this.subtreeDepth(),
                },
            ),
        )}">${build(rootNode, [], 1, 1, 1)}</ul>`;
        this.wireOutline();
        this.markActive();
    }

    outlineItems() {
        return Array.from(
            this.outlineBox.querySelectorAll('[role="treeitem"]'),
        );
    }

    // WAI-ARIA APG tree pattern: one tab stop, roving tabindex inside.
    wireOutline() {
        const tree = this.outlineBox.querySelector('[role="tree"]');
        if (!tree) return;
        const items = this.outlineItems();
        if (!items.length) return;
        const current =
            items.find((i) => i.dataset.id === this.activeNodeId) || items[0];
        current.tabIndex = 0;

        const focusItem = (item) => {
            if (!item) return;
            items.forEach((i) => {
                i.tabIndex = -1;
            });
            item.tabIndex = 0;
            item.focus();
        };

        tree.addEventListener("click", (e) => {
            const li =
                e.target.closest && e.target.closest('[role="treeitem"]');
            if (!li || !tree.contains(li)) return;
            e.stopPropagation();
            focusItem(li);
            if (li.hasAttribute("aria-expanded") && !this.query)
                this.toggle(li.dataset.id);
            this.select(li.dataset.id);
        });

        tree.addEventListener("keydown", (e) => {
            const li =
                e.target.closest && e.target.closest('[role="treeitem"]');
            if (!li) return;
            const list = this.outlineItems();
            const i = list.indexOf(li);
            const expanded = li.getAttribute("aria-expanded");
            switch (e.key) {
                case "ArrowDown":
                    e.preventDefault();
                    focusItem(list[Math.min(list.length - 1, i + 1)]);
                    break;
                case "ArrowUp":
                    e.preventDefault();
                    focusItem(list[Math.max(0, i - 1)]);
                    break;
                case "ArrowRight":
                    e.preventDefault();
                    if (expanded === "false") this.toggle(li.dataset.id);
                    else if (expanded === "true") focusItem(list[i + 1]);
                    break;
                case "ArrowLeft": {
                    e.preventDefault();
                    if (expanded === "true") {
                        this.toggle(li.dataset.id);
                        break;
                    }
                    const parent =
                        li.parentElement &&
                        li.parentElement.closest('[role="treeitem"]');
                    if (parent) focusItem(parent);
                    break;
                }
                case "Home":
                    e.preventDefault();
                    focusItem(list[0]);
                    break;
                case "End":
                    e.preventDefault();
                    focusItem(list[list.length - 1]);
                    break;
                case "Enter":
                case " ":
                case "Spacebar":
                    e.preventDefault();
                    this.select(li.dataset.id);
                    break;
                case "*": {
                    e.preventDefault();
                    // Expand every sibling at this level, per the APG.
                    const siblings = Array.from(
                        li.parentElement.children,
                    ).filter(
                        (c) =>
                            c.getAttribute &&
                            c.getAttribute("role") === "treeitem",
                    );
                    siblings.forEach((s) => this.expanded.add(s.dataset.id));
                    this.draw();
                    break;
                }
                default:
                    // Type-ahead: jump to the next item starting with the character.
                    if (e.key.length === 1 && /\S/.test(e.key)) {
                        const ch = e.key.toLowerCase();
                        const after = list
                            .slice(i + 1)
                            .concat(list.slice(0, i + 1));
                        const hit = after.find((x) => {
                            const nd = this.byId.get(x.dataset.id);
                            return (
                                nd &&
                                String(nd.name || "")
                                    .toLowerCase()
                                    .startsWith(ch)
                            );
                        });
                        if (hit) focusItem(hit);
                    }
            }
        });
    }

    // -- toolbar + pan ------------------------------------------------------

    wireTools() {
        const q = el("ms-ge-struct-q");
        if (q) {
            q.addEventListener("input", () => {
                this.query = q.value.trim().toLowerCase();
                if (this.modelId) this.draw();
            });
        }
        const expand = el("ms-ge-struct-expand");
        if (expand) expand.addEventListener("click", () => this.expandAll());
        const collapse = el("ms-ge-struct-collapse");
        if (collapse)
            collapse.addEventListener("click", () => this.collapseAll());
        const sem = el("ms-ge-struct-semantic");
        if (sem) {
            sem.addEventListener("change", () => {
                this.showSemantic = sem.checked;
                if (this.modelId) this.draw();
            });
        }
        const cid = el("ms-ge-struct-cidoc");
        if (cid) {
            cid.addEventListener("change", () => {
                this.showAllCidoc = cid.checked;
                if (this.modelId) this.draw();
            });
        }
        const outlineBtn = el("ms-ge-struct-outline-btn");
        if (outlineBtn) {
            outlineBtn.addEventListener("click", () => {
                this.outlineOpen = !this.outlineOpen;
                outlineBtn.setAttribute(
                    "aria-pressed",
                    String(this.outlineOpen),
                );
                const pane = el("ms-ge-pane-structure");
                if (pane)
                    pane.classList.toggle("show-outline", this.outlineOpen);
            });
        }
    }

    // Drag pans the scroll box. Nodes are NOT draggable here: unlike the ego
    // network, position carries meaning (depth = column, order = alphabetical),
    // so letting anyone move a node would be letting them lie about the model.
    wirePan() {
        const box = this.scroll;
        if (!box) return;
        let down = null;
        const MOVE_THRESHOLD = 4; // same click-vs-drag threshold as the ego view
        box.addEventListener("pointerdown", (e) => {
            if (e.target.closest && e.target.closest(".ms-ge-st-target"))
                return;
            down = {
                x: e.clientX,
                y: e.clientY,
                sl: box.scrollLeft,
                st: box.scrollTop,
            };
            this._panned = false;
        });
        box.addEventListener("pointermove", (e) => {
            if (!down) return;
            const dx = e.clientX - down.x;
            const dy = e.clientY - down.y;
            if (!this._panned && Math.hypot(dx, dy) <= MOVE_THRESHOLD) return;
            this._panned = true;
            box.classList.add("is-panning");
            box.scrollLeft = down.sl - dx;
            box.scrollTop = down.st - dy;
        });
        const end = () => {
            down = null;
            box.classList.remove("is-panning");
            // Let the click that terminates a pan be swallowed, then re-arm.
            setTimeout(() => {
                this._panned = false;
            }, 0);
        };
        box.addEventListener("pointerup", end);
        box.addEventListener("pointercancel", end);
        box.addEventListener("pointerleave", end);
    }
}

// ---------------------------------------------------------------------------
// item 8 — the table view (a peer, not a hidden <details>)
// ---------------------------------------------------------------------------

const TABLE_COLUMNS = [
    { key: "name", label: () => t("msGeColModel", "Model"), numeric: false },
    { key: "group", label: () => t("msGeColFamily", "Family"), numeric: false },
    {
        key: "fields",
        label: () => t("msGeStatFields", "fields"),
        numeric: true,
    },
    { key: "records", label: () => t("msGeRecords", "records"), numeric: true },
    { key: "links", label: () => t("msGeColLinks", "Links"), numeric: true },
];

function tableRows() {
    const { relations, byId, degree } = state.index;
    const nameById = new Map(state.index.models.map((m) => [m.id, m.name]));
    return state.index.models
        .filter((m) => state.activeGroups.has(m.group))
        .map((m) => ({
            model: m,
            name: m.name,
            group:
                groupLabel(
                    state.data,
                    (state.data.groups || []).find((g) => g.id === m.group),
                ) || m.group,
            fields: (m.counts || {}).nodes || 0,
            records: Number(m.instances) || 0,
            links: degree.get(m.id) || 0,
            out: relations
                .filter((r) => r.source === m.id && byId.has(r.target))
                .map((r) => ({
                    other: nameById.get(r.target) || r.target,
                    property: r.property,
                    count: r.count,
                })),
            inc: relations
                .filter((r) => r.target === m.id && byId.has(r.source))
                .map((r) => ({
                    other: nameById.get(r.source) || r.source,
                    property: r.property,
                    count: r.count,
                })),
        }));
}

// The Fields mode: one row per node across all 12 models — the flat, sortable,
// copy-pasteable rendering of exactly the same trees the Structure view draws.
// This is the artefact researchers actually export.
const FIELD_COLUMNS = [
    { key: "model", label: () => t("msGeColModel", "Model") },
    { key: "path", label: () => t("msGeColPath", "Path") },
    { key: "name", label: () => t("msGeColField", "Field") },
    { key: "datatype", label: () => t("msGeColDatatype", "Datatype") },
    { key: "cidoc", label: () => t("msGeColCidoc", "CIDOC class") },
    { key: "property", label: () => t("msGeColProperty", "Property") },
    { key: "required", label: () => t("msGeColRequired", "Required") },
    { key: "cardinality", label: () => t("msGeColCardinality", "Cardinality") },
    { key: "target", label: () => t("msGeColTarget", "Target") },
];

function fieldRows() {
    const rows = [];
    state.index.models
        .filter((m) => state.activeGroups.has(m.group))
        .forEach((m) => {
            const st = m.structure || { root: null, nodes: [] };
            const byId = new Map((st.nodes || []).map((n) => [n.id, n]));
            const pathOf = (n) => {
                const parts = [];
                let cur = byId.get(n.parent);
                while (cur && cur.id !== st.root) {
                    parts.unshift(cur.name);
                    cur = byId.get(cur.parent);
                }
                return parts.join(" › ");
            };
            (st.nodes || []).forEach((n) => {
                if (n.id === st.root) return; // the root is the model, not a field
                rows.push({
                    modelId: m.id,
                    model: m.name,
                    path: pathOf(n),
                    name: n.name,
                    datatype: n.datatype,
                    cidoc: n.cidoc || "",
                    property: n.property || "",
                    required: n.required ? t("msGeYes", "Yes") : "",
                    cardinality: n.is_collector
                        ? n.cardinality === "n"
                            ? t("msGeStructCardN", "Repeatable")
                            : t("msGeStructCard1", "Once")
                        : "",
                    target: ((n.config || {}).target_graphs || [])
                        .map((id) => (state.index.byId.get(id) || {}).name)
                        .filter(Boolean)
                        .join(", "),
                });
            });
        });
    return rows;
}

function renderFieldsTable(box) {
    const { key, dir } = state.fieldSort;
    const rows = fieldRows().sort(
        (a, b) =>
            String(a[key]).localeCompare(String(b[key])) * dir ||
            a.model.localeCompare(b.model) ||
            a.path.localeCompare(b.path) ||
            a.name.localeCompare(b.name),
    );
    const models = new Set(rows.map((r) => r.modelId)).size;
    const head = FIELD_COLUMNS.map((c) => {
        const active = c.key === key;
        const sortAttr = active
            ? dir === 1
                ? "ascending"
                : "descending"
            : "none";
        return `<th scope="col" aria-sort="${sortAttr}"><button type="button" class="ms-ge-tbl-sort${
            active ? " is-active" : ""
        }" data-fkey="${esc(c.key)}">${esc(c.label())}<span class="ms-ge-tbl-caret" aria-hidden="true"></span></button></th>`;
    }).join("");

    // SECURITY: every cell below is DB-authored payload text — model/field names,
    // CIDOC classes, prettified properties, target model names — all esc()'d.
    box.innerHTML = `
        <table class="ms-ge-tbl ms-ge-tbl-fields">
            <caption class="ms-ge-sr">${esc(
                tv(
                    "msGeFieldsCaption",
                    "Every field of every model: {n} rows across {m} models.",
                    {
                        n: rows.length,
                        m: models,
                    },
                ),
            )}</caption>
            <thead><tr>${head}</tr></thead>
            <tbody>${rows
                .map(
                    (r) => `
                <tr data-id="${esc(r.modelId)}">
                    <th scope="row"><button type="button" class="ms-ge-tbl-struct" data-id="${esc(
                        r.modelId,
                    )}">${esc(r.model)}</button></th>
                    <td class="ms-ge-tbl-path">${r.path ? esc(r.path) : '<span class="text-muted">—</span>'}</td>
                    <td>${esc(r.name)}</td>
                    <td><span class="ms-ge-dt" style="--c:${esc(
                        datatypeColor(state.data.datatypes, r.datatype),
                    )}">${esc(r.datatype)}</span></td>
                    <td>${esc(r.cidoc)}</td>
                    <td>${esc(r.property)}</td>
                    <td>${esc(r.required)}</td>
                    <td>${esc(r.cardinality)}</td>
                    <td>${esc(r.target)}</td>
                </tr>`,
                )
                .join("")}</tbody>
        </table>`;

    box.querySelectorAll(".ms-ge-tbl-sort").forEach((btn) =>
        btn.addEventListener("click", () => {
            const k = btn.dataset.fkey;
            if (state.fieldSort.key === k) state.fieldSort.dir *= -1;
            else state.fieldSort = { key: k, dir: 1 };
            renderTable();
        }),
    );
    box.querySelectorAll(".ms-ge-tbl-struct").forEach((btn) =>
        btn.addEventListener("click", () => openStructure(btn.dataset.id)),
    );
}

function renderTable() {
    const box = el("ms-ge-table");
    if (!box) return;
    if (state.tableMode === "fields") {
        renderFieldsTable(box);
        applyQueryToTable();
        return;
    }
    const { key, dir } = state.tableSort;
    const rows = tableRows().sort((a, b) => {
        const col = TABLE_COLUMNS.find((c) => c.key === key);
        if (col && col.numeric)
            return (a[key] - b[key]) * dir || a.name.localeCompare(b.name);
        return (
            String(a[key]).localeCompare(String(b[key])) * dir ||
            a.name.localeCompare(b.name)
        );
    });

    const relList = (items, arrow) =>
        items.length
            ? `<ul class="ms-ge-tbl-rels">${items
                  .map(
                      (r) =>
                          `<li><span class="ms-ge-tbl-arrow" aria-hidden="true">${arrow}</span><b>${esc(r.other)}</b><em>${esc(r.property)}</em>${Number(r.count) > 1 ? `<span class="ms-ge-rel-count">${esc(r.count)}</span>` : ""}</li>`,
                  )
                  .join("")}</ul>`
            : `<span class="text-muted">—</span>`;

    const head = TABLE_COLUMNS.map((c) => {
        const active = c.key === key;
        const sortAttr = active
            ? dir === 1
                ? "ascending"
                : "descending"
            : "none";
        return `<th scope="col" class="${c.numeric ? "is-num" : ""}" aria-sort="${sortAttr}"><button type="button" class="ms-ge-tbl-sort${active ? " is-active" : ""}" data-key="${esc(c.key)}">${esc(c.label())}<span class="ms-ge-tbl-caret" aria-hidden="true"></span></button></th>`;
    }).join("");

    box.innerHTML = `
        <table class="ms-ge-tbl">
            <caption class="ms-ge-sr">${esc(tv("msGeTableCaption", "Every model with its outgoing and incoming typed relationships. {n} models, {r} relationships.", { n: rows.length, r: state.index.relations.length }))}</caption>
            <thead><tr>${head}<th scope="col">${esc(t("msGeColOutgoing", "Outgoing"))}</th><th scope="col">${esc(t("msGeColIncoming", "Incoming"))}</th></tr></thead>
            <tbody>${rows
                .map(
                    (r) => `
                <tr data-id="${esc(r.model.id)}">
                    <th scope="row"><button type="button" class="ms-ge-tbl-model" data-id="${esc(r.model.id)}">${esc(r.name)}</button></th>
                    <td>${esc(r.group)}</td>
                    <td class="is-num">${esc(r.fields)}</td>
                    <td class="is-num">${r.records ? esc(r.records) : `<span class="text-muted">0</span>`}</td>
                    <td class="is-num">${esc(r.links)}</td>
                    <td>${relList(r.out, "→")}</td>
                    <td>${relList(r.inc, "←")}</td>
                </tr>`,
                )
                .join("")}</tbody>
        </table>`;

    box.querySelectorAll(".ms-ge-tbl-sort").forEach((btn) =>
        btn.addEventListener("click", () => {
            const k = btn.dataset.key;
            const col = TABLE_COLUMNS.find((c) => c.key === k);
            if (state.tableSort.key === k) state.tableSort.dir *= -1;
            else state.tableSort = { key: k, dir: col && col.numeric ? -1 : 1 };
            renderTable();
        }),
    );
    box.querySelectorAll(".ms-ge-tbl-model").forEach((btn) =>
        btn.addEventListener("click", () => {
            const model = state.index.byId.get(btn.dataset.id);
            if (!model) return;
            ego.setFocus(model.id);
            openDrawer(model, state.data, btn);
        }),
    );
    applyQueryToTable();
    markSelection();
}

function applyQueryToTable() {
    const box = el("ms-ge-table");
    if (!box) return;
    box.querySelectorAll("tbody tr").forEach((tr) => {
        const model = state.index.byId.get(tr.dataset.id);
        tr.classList.toggle(
            "is-dim",
            Boolean(state.query) && model && !matchesQuery(model),
        );
    });
}

// Keep the selected model visibly marked in every view — the drawer now pushes
// the stage aside rather than covering it (item 6), so "which one am I reading?"
// has to stay answerable.
function markSelection() {
    const id = state.selectedId;
    document
        .querySelectorAll(".ms-ge-mx-rowh, .ms-ge-mx-colh, .ms-ge-tbl tbody tr")
        .forEach((n) => {
            const nodeId = n.dataset.id;
            n.classList.toggle("is-selected", Boolean(id) && nodeId === id);
        });
    if (ego)
        ego.nodeEls.forEach(({ g, n }) =>
            g.classList.toggle("is-selected", n.id === id),
        );
}

// ---------------------------------------------------------------------------
// item 6 — the drawer
// ---------------------------------------------------------------------------

const NG_OPEN_COUNT = 3;

function openDrawer(model, data, trigger, highlightTargetId) {
    const drawer = el("ms-ge-drawer");
    const body = el("ms-ge-drawer-body");
    const stage = el("ms-ge-stage");
    const groups = data.groups || [];
    const group = groups.find((g) => g.id === model.group);
    const gcolor = groupColor(groups, model.group);
    const glabel = groupLabel(data, group) || model.group;

    state.selectedId = model.id;

    // SECURITY: model.name/description/cidoc, ng.name, nd.name/datatype/cidoc and
    // every relation property/label below are DB-authored (graph designer content)
    // rendered on an anonymous public page — all of them are esc()'d before they
    // enter this innerHTML string.
    const nodegroups = model.nodegroups || [];
    const fieldsHtml = nodegroups
        .map((ng, i) => {
            const fields = (ng.nodes || [])
                .map((nd) => {
                    const isRel = RELATION_DATATYPES.has(nd.datatype);
                    return `
                <div class="ms-ge-field" data-name="${esc(String(nd.name || "").toLowerCase())}" data-dt="${esc(String(nd.datatype || "").toLowerCase())}" data-rel="${isRel ? "1" : "0"}">
                    <span class="ms-ge-dt" style="--c:${esc(datatypeColor(data.datatypes, nd.datatype))}">${esc(nd.datatype)}</span>
                    <span class="ms-ge-field-name">${esc(nd.name)}</span>
                    ${nd.cidoc ? `<span class="ms-ge-field-cidoc">${esc(nd.cidoc)}</span>` : ""}
                    ${nd.required ? `<span class="ms-ge-badge">${esc(t("msGeRequired", "required"))}</span>` : ""}
                </div>`;
                })
                .join("");
            // Person carries 62 fields across 23 nodegroups. Dumped flat that is a
            // scroll, not a schema — so everything past the first three collapses.
            return `
        <details class="ms-ge-ng" data-ng ${i < NG_OPEN_COUNT ? "open" : ""}>
            <summary><span class="ms-ge-ng-name">${esc(ng.name) || "—"}</span><span class="ms-ge-ng-count">${esc((ng.nodes || []).length)}</span></summary>
            ${fields}
        </details>`;
        })
        .join("");

    const rels = (data.relations || []).filter(
        (r) => r.source === model.id || r.target === model.id,
    );
    const nameById = new Map((data.models || []).map((m) => [m.id, m.name]));
    const relHtml = rels.length
        ? rels
              .map((r) => {
                  const other = r.source === model.id ? r.target : r.source;
                  const dir = r.source === model.id ? "→" : "←";
                  const otherName = nameById.get(other) || other;
                  // r.count/r.fields record how many distinct fields on the model
                  // produced this typed relationship — badge + tooltip when > 1.
                  const countBadge =
                      r.count > 1
                          ? `<span class="ms-ge-rel-count" title="${esc((r.fields || []).join(", "))}">${esc(r.count)}</span>`
                          : "";
                  const hot =
                      highlightTargetId && other === highlightTargetId
                          ? " is-hot"
                          : "";
                  // r.label is the originating field's human name (e.g. "Related
                  // work"), distinct from r.property (the prettified CIDOC-CRM
                  // property) — surfaced as a native tooltip on the whole row.
                  return `<button class="ms-ge-rel${hot}" data-focus="${esc(other)}" title="${esc(r.label)}">${dir} ${esc(otherName)} <em>${esc(r.property)}</em>${countBadge}</button>`;
              })
              .join("")
        : `<p class="text-muted">${esc(t("msGeNoRelations", "No relations"))}</p>`;

    const records = Number(model.instances) || 0;

    body.innerHTML = `
        <div class="ms-ge-drawer-head">
            <!-- The group hue is handed over as \`--c\`, not as \`background\`, so
                 pages.scss can render this chip as a tint + ink text + coloured
                 border. As a solid fill behind #fff it measured 2.54-4.23:1. -->
            <span class="ms-ge-drawer-group" style="--c:${esc(gcolor)}">${esc(glabel)}</span>
            <h3>${esc(model.name)}</h3>
            <div class="ms-ge-drawer-meta">
                ${model.cidoc ? `<span class="ms-ge-chip">${esc(model.cidoc)}</span>` : ""}
                <!-- WAVE 4c: an empty model used to read as a bare "0 records"
                     chip, which looks like a failure rather than like a model
                     that is finished and waiting for its first deposit. -->
                ${
                    records
                        ? `<span class="ms-ge-chip">${esc(records)} ${esc(t("msGeRecords", "records"))}</span>`
                        : `<span class="ms-ge-chip is-empty">${esc(t("msGeNoRecordsYet", "No records published yet — model defined and open for deposit."))}</span>`
                }
                <span class="ms-ge-chip">${esc(model.counts.nodegroups)} ${esc(t("msGeNodegroups", "field groups"))}</span>
            </div>
            ${model.description ? `<p class="ms-ge-drawer-desc">${esc(model.description)}</p>` : ""}
            <button type="button" class="ms-ge-struct-open" data-model="${esc(model.id)}">${esc(t("msGeStructOpen", "View structure →"))}</button>
        </div>
        <div class="ms-ge-tabs" role="tablist">
            <!-- item 6: Relations opens first. Relationships are the thesis of this
                 page; the field list is the reference material behind it. -->
            <button class="ms-ge-tab is-active" data-tab="relations" role="tab" aria-selected="true">${esc(t("msGeRelations", "Relations"))}</button>
            <button class="ms-ge-tab" data-tab="fields" role="tab" aria-selected="false">${esc(t("msGeFields", "Fields"))}</button>
        </div>
        <div class="ms-ge-tabpane" data-pane="relations">
            ${rels.length ? `<p class="ms-ge-rel-hint">${esc(t("msGeTargets", "→ target · ← source"))}</p>` : ""}
            ${relHtml}
        </div>
        <div class="ms-ge-tabpane" data-pane="fields" hidden>
            <!-- Highest-intent moment: this flat list of 23 "nodegroups" is exactly
                 what the Structure view replaces with the hierarchy they really form. -->
            <button type="button" class="ms-ge-struct-open is-inline" data-model="${esc(model.id)}">${esc(t("msGeStructOpen", "View structure →"))}</button>
            <div class="ms-ge-fieldtools">
                <input type="search" class="ms-ge-fieldfilter" id="ms-ge-fieldfilter" placeholder="${esc(t("msGeFieldFilter", "Filter fields…"))}" aria-label="${esc(t("msGeFieldFilter", "Filter fields…"))}">
                <label class="ms-ge-relonly"><input type="checkbox" id="ms-ge-relonly"> ${esc(t("msGeRelationsOnly", "Relation fields only"))}</label>
            </div>
            <p class="text-muted ms-ge-nofields" id="ms-ge-nofields" hidden>${esc(t("msGeNoFields", "No field matches."))}</p>
            ${fieldsHtml}
        </div>`;

    body.querySelectorAll(".ms-ge-tab").forEach((tab) =>
        tab.addEventListener("click", () => {
            body.querySelectorAll(".ms-ge-tab").forEach((x) => {
                const on = x === tab;
                x.classList.toggle("is-active", on);
                x.setAttribute("aria-selected", String(on));
            });
            body.querySelectorAll(".ms-ge-tabpane").forEach((p) => {
                p.hidden = p.dataset.pane !== tab.dataset.tab;
            });
        }),
    );
    body.querySelectorAll(".ms-ge-rel").forEach((b) =>
        b.addEventListener("click", () => {
            const target = state.index.byId.get(b.dataset.focus);
            if (!target) return;
            ego.setFocus(target.id);
            openDrawer(target, state.data, b);
        }),
    );
    body.querySelectorAll(".ms-ge-struct-open").forEach((b) =>
        b.addEventListener("click", () => openStructure(b.dataset.model)),
    );
    wireFieldTools(body);

    drawerTrigger = trigger || el("ms-ge-canvas");

    // item 6 — the drawer used to be `position:absolute; right:0` inside a 560px
    // stage, so it covered the very node you had just clicked. It is now a real
    // grid column: the stage becomes `1fr 380px` and the views shrink to fit.
    if (stage) stage.classList.add("has-drawer");

    // [hidden] is display:none, so adding .open in the same tick as unhiding
    // leaves no box to transition from and the slide-in never plays. Unhide
    // first, then add .open (and move focus in) on the next frame.
    drawer.hidden = false;
    requestAnimationFrame(() => {
        drawer.classList.add("open");
        const closeBtn = el("ms-ge-drawer-close");
        if (closeBtn) closeBtn.focus();
        if (ego) ego.reflow();
    });
    markSelection();
    // Through updateHash(), not a direct write: the direct `#model=…` used to
    // wipe the view/root/node segments a structure deep link had just set.
    updateHash();
}

// Entry point shared by the drawer buttons, the Fields table and the deep link.
function openStructure(modelId, nodeId) {
    if (!structure || !state.index.byId.has(modelId)) return;
    structure.setModel(modelId);
    showView("structure");
    if (nodeId && structure.byId.has(nodeId)) structure.select(nodeId);
    else updateHash();
}

// ---------------------------------------------------------------------------
// The node inspector — the drawer's SECOND job.
//
// Risk 4 in the spec: one drawer, two contents. The header is therefore visibly
// different (an eyebrow naming the model + the node's own name as the heading,
// against the model view's family chip + model name), and `.is-node` lets
// pages.scss style the two apart. Anything less and the reader cannot tell
// whether they are reading a model or a field.
// ---------------------------------------------------------------------------
function openNodeInspector(view, node) {
    const drawer = el("ms-ge-drawer");
    const body = el("ms-ge-drawer-body");
    const stage = el("ms-ge-stage");
    if (!drawer || !body || !node) return;
    const model = view.model || {};
    const path = view.ancestors(node.id).filter((a) => a.id !== view.modelRoot);
    const targets = view.targetModels(node);
    // Prefer the RDM label ("Pigments (312)") over the raw collection UUID —
    // the payload ships collection_label/collection_size when the RDM has them.
    const cfg = node.config || {};
    const collection = cfg.collection_label
        ? `${cfg.collection_label}${cfg.collection_size ? ` (${cfg.collection_size})` : ""}`
        : cfg.collection;

    // CONTRACT: `value` is interpolated raw, because two callers need real markup
    // (the CIDOC/property links and the breadcrumb's separators). Every call site
    // below therefore passes either a link(...) result or an esc(...) result —
    // never a bare payload string. `label` is always a translation key, but is
    // esc()'d anyway so the rule "everything into innerHTML is escaped" has no
    // exception a reader has to remember.
    const row = (label, value) =>
        value
            ? `<div class="ms-ge-insp-row"><dt>${esc(label)}</dt><dd>${value}</dd></div>`
            : "";

    // SECURITY: node.name / datatype / cidoc / property / config values and every
    // model name below are DB-authored and reach an anonymous page — esc() on all
    // of them.
    //
    // The two URIs need MORE than esc(): they come from `Node.ontologyclass` and
    // `Edge.ontologyproperty`, which a graph designer sets freely, and they land
    // in an href. esc() makes `javascript:alert(1)` harmless as *text* but not as
    // a *scheme* — and encodeURI() does not touch it either. So the scheme is
    // allowlisted and anything else degrades to plain text.
    const safeHref = (uri) => {
        const s = String(uri ?? "").trim();
        return /^https?:\/\//i.test(s) ? s : "";
    };
    const link = (uri, text) => {
        const href = safeHref(uri);
        return href
            ? `<a href="${esc(encodeURI(href))}" target="_blank" rel="noopener">${esc(text)}</a>`
            : esc(text);
    };

    const crumb = path.length
        ? path
              .map((a) => esc(a.name))
              .join('<span aria-hidden="true"> › </span>')
        : "";

    const targetHtml = targets
        .map(
            (tm) =>
                `<button type="button" class="ms-ge-insp-target" data-model="${esc(tm.id)}" title="${esc(
                    tv("msGeStructLinksTo", "Links to {model}", {
                        model: tm.name,
                    }),
                )}">${esc(
                    tv("msGeStructViewModel", "View {model} →", {
                        model: tm.name,
                    }),
                )}</button>`,
        )
        .join("");

    body.innerHTML = `
        <div class="ms-ge-drawer-head is-node">
            <span class="ms-ge-insp-eyebrow">${esc(model.name || "")}</span>
            <h3>${esc(node.name)}${
                node.required
                    ? `<span class="ms-ge-insp-req" aria-hidden="true"> ∗</span>`
                    : ""
            }</h3>
            <div class="ms-ge-drawer-meta">
                <span class="ms-ge-dt" style="--c:${esc(
                    datatypeColor(view.data.datatypes, node.datatype),
                )}">${esc(node.datatype)}</span>
                ${
                    node.is_collector
                        ? `<span class="ms-ge-chip">${esc(t("msGeStructGroup", "Field group"))}</span>`
                        : ""
                }
                <span class="ms-ge-chip">${esc(
                    node.required
                        ? t("msGeStructRequired", "Required")
                        : t("msGeStructOptional", "Optional"),
                )}</span>
            </div>
            ${
                node.datatype === "semantic"
                    ? `<p class="ms-ge-drawer-desc">${esc(
                          t(
                              "msGeStructSemantic",
                              "Structural node — carries no data",
                          ),
                      )}</p>`
                    : ""
            }
        </div>
        <dl class="ms-ge-insp">
            ${row(t("msGeStructCidoc", "CIDOC-CRM class"), node.cidoc ? link(node.cidoc_uri, node.cidoc) : "")}
            ${row(
                t("msGeStructFromParent", "From parent"),
                node.property ? link(node.property_uri, node.property) : "",
            )}
            ${row(t("msGeStructPath", "Path"), crumb)}
            ${row(
                t("msGeStructCardinality", "Cardinality"),
                node.is_collector
                    ? esc(
                          node.cardinality === "n"
                              ? t("msGeStructCardN", "Repeatable")
                              : t("msGeStructCard1", "Once"),
                      )
                    : "",
            )}
            ${row(t("msGeStructCollection", "Controlled vocabulary"), collection ? esc(collection) : "")}
        </dl>
        ${targetHtml ? `<div class="ms-ge-insp-targets">${targetHtml}</div>` : ""}
        ${
            targets.length
                ? `<button type="button" class="ms-ge-insp-network" data-target="${esc(
                      targets[0].id,
                  )}">${esc(
                      t(
                          "msGeStructSeeNetwork",
                          "See this relationship in the Network view",
                      ),
                  )}</button>`
                : ""
        }`;

    body.querySelectorAll(".ms-ge-insp-target").forEach((b) =>
        b.addEventListener("click", () => openStructure(b.dataset.model)),
    );
    const net = body.querySelector(".ms-ge-insp-network");
    if (net) {
        net.addEventListener("click", () => {
            // The ego network's edges are DERIVED from these resource-instance
            // nodes, so this is the same fact seen from the other side.
            const m = state.index.byId.get(view.modelId);
            if (!m) return;
            showView("network");
            ego.setFocus(m.id);
            openDrawer(m, state.data, net, net.dataset.target);
        });
    }

    if (stage) stage.classList.add("has-drawer");
    drawer.hidden = false;
    requestAnimationFrame(() => drawer.classList.add("open"));
}

function wireFieldTools(body) {
    const filter = body.querySelector("#ms-ge-fieldfilter");
    const relOnly = body.querySelector("#ms-ge-relonly");
    const none = body.querySelector("#ms-ge-nofields");
    if (!filter || !relOnly) return;
    const apply = () => {
        const q = filter.value.trim().toLowerCase();
        const onlyRel = relOnly.checked;
        let shown = 0;
        body.querySelectorAll("[data-ng]").forEach((ng) => {
            let visible = 0;
            ng.querySelectorAll(".ms-ge-field").forEach((f) => {
                const ok =
                    (!onlyRel || f.dataset.rel === "1") &&
                    (!q ||
                        f.dataset.name.includes(q) ||
                        f.dataset.dt.includes(q));
                f.hidden = !ok;
                if (ok) visible += 1;
            });
            ng.hidden = visible === 0;
            if (visible && (q || onlyRel)) ng.open = true;
            shown += visible;
        });
        if (none) none.hidden = shown > 0;
    };
    filter.addEventListener("input", apply);
    relOnly.addEventListener("change", apply);
}

function closeDrawer() {
    const drawer = el("ms-ge-drawer");
    const stage = el("ms-ge-stage");
    if (!drawer || drawer.hidden) return;
    drawer.classList.remove("open");
    if (stage) stage.classList.remove("has-drawer");
    state.selectedId = null;
    markSelection();
    let finished = false;
    const finish = () => {
        if (finished) return;
        finished = true;
        drawer.removeEventListener("transitionend", onTransitionEnd);
        drawer.hidden = true;
        if (ego) ego.reflow();
    };
    const onTransitionEnd = (e) => {
        if (e.target === drawer) finish();
    };
    drawer.addEventListener("transitionend", onTransitionEnd);
    setTimeout(finish, 320); // fallback if transitionend doesn't fire (0.28s CSS transition)

    const back = drawerTrigger || el("ms-ge-canvas");
    drawerTrigger = null;
    if (back && typeof back.focus === "function" && document.contains(back))
        back.focus();
    else {
        const canvas = el("ms-ge-canvas");
        if (canvas) canvas.focus();
    }
}

// Esc-to-close + close-button listeners are wired exactly once, regardless of
// how many times openDrawer()/render() run.
function wireDrawerChrome() {
    if (drawerChromeWired) return;
    drawerChromeWired = true;
    const closeBtn = el("ms-ge-drawer-close");
    if (closeBtn) closeBtn.addEventListener("click", closeDrawer);
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") closeDrawer();
    });
}

// ---------------------------------------------------------------------------
// Views / sorts / search
// ---------------------------------------------------------------------------

const PANES = {
    matrix: "ms-ge-pane-matrix",
    network: "ms-ge-pane-network",
    structure: "ms-ge-pane-structure",
    datatypes: "ms-ge-pane-datatypes",
    table: "ms-ge-pane-table",
};

let plotted = false;
let plotlyData = null;

// Extracted from the click handler so a deep link (#view=structure) and the
// drawer's "View structure →" buttons can switch views without synthesising a
// click on a tab.
async function showView(view) {
    state.view = view;
    document.querySelectorAll(".ms-ge-view").forEach((b) => {
        const on = b.dataset.view === view;
        b.classList.toggle("is-active", on);
        b.setAttribute("aria-selected", String(on));
    });
    Object.entries(PANES).forEach(([name, id]) => {
        const pane = el(id);
        if (pane) pane.hidden = name !== view;
    });
    // Per-view sub-toolbars: ordering is meaningful only for the matrix, and the
    // model combobox only for the (per-model) structure view.
    const sorts = el("ms-ge-sorts");
    if (sorts) sorts.hidden = view !== "matrix";
    const structTools = el("ms-ge-struct-tools");
    if (structTools) structTools.hidden = view !== "structure";

    // Don't tick/paint an invisible SVG.
    if (view === "network") {
        if (ego) ego.reflow();
    } else if (ego) ego.pause();

    if (view === "structure" && structure) {
        structure.ensureModel();
        structure.draw();
    }

    if (view === "datatypes" && !plotted) {
        const box = el("ms-ge-plotly");
        plotted = true;
        try {
            if (box) box.innerHTML = ""; // clear a previous failure notice
            await drawPlotly(plotlyData, box);
        } catch {
            // Dynamic-import or render failure (offline, bundle missing…).
            // Reset the latch so reopening the tab retries instead of leaving
            // the pane empty forever.
            plotted = false;
            if (box) {
                box.innerHTML = `<div class="ms-ge-error">${esc(
                    t(
                        "msGeChartError",
                        "The chart could not be loaded — reopen this tab to retry.",
                    ),
                )}</div>`;
            }
        }
    }
}

function wireViews(data) {
    plotlyData = data;
    document
        .querySelectorAll(".ms-ge-view")
        .forEach((btn) =>
            btn.addEventListener("click", () => showView(btn.dataset.view)),
        );
}

function wireTableModes() {
    document.querySelectorAll(".ms-ge-tbl-mode").forEach((btn) =>
        btn.addEventListener("click", () => {
            state.tableMode = btn.dataset.mode;
            document.querySelectorAll(".ms-ge-tbl-mode").forEach((b) => {
                const on = b === btn;
                b.classList.toggle("is-active", on);
                b.setAttribute("aria-pressed", String(on));
            });
            renderTable();
        }),
    );
}

function wireSorts() {
    document.querySelectorAll(".ms-ge-sort").forEach((btn) =>
        btn.addEventListener("click", () => {
            state.matrixSort = btn.dataset.sort;
            document.querySelectorAll(".ms-ge-sort").forEach((b) => {
                const on = b === btn;
                b.classList.toggle("is-active", on);
                b.setAttribute("aria-pressed", String(on));
            });
            renderMatrix();
        }),
    );
}

function wireSearch() {
    const input = el("ms-ge-search");
    const count = el("ms-ge-search-count");
    if (!input) return; // the one element this file otherwise dereferences unguarded
    // item 7 — this was bound to `change`, so typing did nothing at all until the
    // field lost focus. On `input`, with a live match count and an explicit
    // no-match state.
    const run = () => {
        state.query = input.value.trim().toLowerCase();
        const models = state.index.models;
        const hits = models.filter(matchesQuery);
        if (count) {
            if (!state.query) count.textContent = "";
            else if (!hits.length)
                count.textContent = t("msGeNoMatch", "No model matches");
            else
                count.textContent = tv("msGeMatchCount", "{n} of {total}", {
                    n: hits.length,
                    total: models.length,
                });
        }
        if (count)
            count.classList.toggle(
                "is-none",
                Boolean(state.query) && !hits.length,
            );
        applyQueryToMatrix();
        applyQueryToTable();
        if (ego) ego.applyQuery();
        // A single unambiguous hit re-centres the drill-down, so typing a name
        // still gets you somewhere.
        if (hits.length === 1) {
            if (ego) ego.setFocus(hits[0].id);
            if (ego) ego.applyQuery();
        }
    };
    input.addEventListener("input", run);

    document.querySelectorAll(".ms-ge-filter").forEach((f) =>
        f.addEventListener("click", () => {
            const on = f.classList.toggle("is-on");
            f.setAttribute("aria-pressed", String(on));
            state.activeGroups = new Set(
                Array.from(
                    document.querySelectorAll(".ms-ge-filter.is-on"),
                ).map((x) => x.dataset.group),
            );
            // item 4 — the ego view is REBUILT (not just repainted) so filtered
            // nodes leave the simulation entirely instead of continuing to push
            // the visible ones around invisibly.
            renderMatrix();
            renderTable();
            if (ego) ego.build();
        }),
    );
}

// ---------------------------------------------------------------------------
// item 10 — the datatype chart
// ---------------------------------------------------------------------------

async function drawPlotly(data, box) {
    // cartesian-dist: all 2D scientific traces (bar, scatter, heatmap,
    // contour, histogram, box/violin) at a third of the full bundle. Swap
    // back to plotly.js-dist only if 3D/geo traces become needed.
    const Plotly = (await import("plotly.js-cartesian-dist")).default;
    // State the sort rather than leaving the reader to infer it.
    const dts = (data.datatypes || [])
        .slice()
        .sort((a, b) => (b.count || 0) - (a.count || 0));
    const bar = {
        type: "bar",
        x: dts.map((d) => plain(d.label)),
        y: dts.map((d) => d.count),
        hovertemplate: "%{x}: %{y}<extra></extra>",
        // Same inversion as the datatype chips in the drawer: a tint with a
        // full-strength outline, so the bars belong to the same visual system
        // and no longer shout at the reader in 16 saturated hues.
        marker: {
            color: dts.map((d) => mixWhite(d.color, 42)),
            line: {
                color: dts.map((d) => contrastSafeStroke(d.color)),
                width: 1.4,
            },
        },
    };
    Plotly.newPlot(
        box,
        [bar],
        {
            title: {
                text: plain(t("msGeDatatypeChartTitle", "Fields by datatype")),
            },
            xaxis: {
                title: {
                    text: plain(
                        t(
                            "msGeChartX",
                            "Datatype (sorted by field count, descending)",
                        ),
                    ),
                },
                automargin: true,
            },
            yaxis: {
                title: { text: plain(t("msGeChartY", "Fields")) },
                automargin: true,
            },
            margin: { t: 50, r: 10, b: 40, l: 20 },
            paper_bgcolor: "transparent",
            plot_bgcolor: "transparent",
            font: { family: "Sora, sans-serif" },
        },
        { displayModeBar: false, responsive: true },
    );
}

document.addEventListener("DOMContentLoaded", boot);
