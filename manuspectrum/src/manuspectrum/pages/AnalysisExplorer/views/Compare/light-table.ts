import { layerTag } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layer-tags.ts";

import type { FileLayer } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

export type TableLayout = "single" | "curtain" | "grid2" | "grid4" | "stack";

export type TableGrouping = "analysis" | "tag";

/** 0 to 200, 100 neutral, as in `iiif-viewer.js`. */
export interface PaneFilters {
    brightness: number;
    contrast: number;
    saturation: number;
    greyscale: boolean;
}

export interface StackLayer {
    canvas: string;
    opacity: number;
    on: boolean;
    tint: string | null;
}

/** What the reader laid on the table and the browser keeps; zoom, pan and the curtain's position are not part of it. */
export interface StoredImaging {
    layout: TableLayout;
    /** Canvas ids (`FileLayer.id`), one per pane A to D. */
    panes: (string | null)[];
    /** Zoom and pan linked across analyses; within one analysis they are linked anyway. */
    linkAll: boolean;
    /** One per pane, then the stack's at index 4. */
    filters: PaneFilters[];
    /** A stack holds layers of one analysis, fixed by the first laid. */
    stack: { analysis: string | null; layers: StackLayer[] };
    grouping: TableGrouping;
}

export interface TableState extends StoredImaging {
    /** The pane the gallery lays into. */
    active: number;
}

export const PANE_COUNT = 4;

export const NEUTRAL_FILTERS: Readonly<PaneFilters> = Object.freeze({
    brightness: 100,
    contrast: 100,
    saturation: 100,
    greyscale: false,
});

export const TABLE_LAYOUTS: readonly TableLayout[] = [
    "single",
    "curtain",
    "grid2",
    "grid4",
    "stack",
];

/** Panes a layout shows. */
export const PANES_SHOWN: Readonly<Record<TableLayout, number>> = {
    single: 1,
    curtain: 2,
    grid2: 2,
    grid4: 4,
    stack: 0,
};

export function neutralFilters(): PaneFilters[] {
    return Array.from({ length: PANE_COUNT + 1 }, () => ({
        ...NEUTRAL_FILTERS,
    }));
}

/** The analyses of the maps in slot order, each with its layers in manifest order. */
interface AnalysisLayers {
    analysis: string;
    layers: FileLayer[];
    /** The layer a one-layer key (`im:`) names. */
    named: string | null;
}

function analysesOf(maps: readonly MapLine[]): AnalysisLayers[] {
    const found = new Map<string, AnalysisLayers>();
    for (const line of [...maps].sort((a, b) => a.slot - b.slot)) {
        const entry = found.get(line.analysis.id) ?? {
            analysis: line.analysis.id,
            layers: [],
            named: null,
        };
        const named = line.file.layers.find(
            (layer) => layer.index === line.named,
        );
        if (entry.named === null && named) entry.named = named.id;
        entry.layers.push(...line.file.layers);
        found.set(line.analysis.id, entry);
    }
    return [...found.values()];
}

function canvasesOf(maps: readonly MapLine[]): Set<string> {
    return new Set(
        maps.flatMap((line) => line.file.layers.map((layer) => layer.id)),
    );
}

function analysisOf(canvas: string, maps: readonly MapLine[]): string | null {
    return (
        maps.find((line) =>
            line.file.layers.some((layer) => layer.id === canvas),
        )?.analysis.id ?? null
    );
}

/** The layer a canvas id names and the map line it belongs to, null when the Selection holds none. */
export function layerById(
    canvas: string,
    maps: readonly MapLine[],
): { layer: FileLayer; line: MapLine } | null {
    for (const line of maps) {
        const layer = line.file.layers.find((entry) => entry.id === canvas);
        if (layer) return { layer, line };
    }
    return null;
}

function sharesFamily(maps: readonly MapLine[]): boolean {
    const seen = new Map<string, string>();
    for (const line of maps) {
        for (const layer of line.file.layers) {
            const family = layerTag(layer)?.family;
            if (!family) continue;
            const other = seen.get(family);
            if (other !== undefined && other !== line.analysis.id) return true;
            seen.set(family, line.analysis.id);
        }
    }
    return false;
}

/** The layout a Selection opens on (spec 6.7). */
export function defaultState(maps: readonly MapLine[]): TableState {
    const analyses = analysesOf(maps);
    const panes: (string | null)[] = Array(PANE_COUNT).fill(null);
    let layout: TableLayout = "single";
    if (analyses.length === 1) {
        const [first] = analyses;
        panes[0] = first.layers[0]?.id ?? null;
        if (first.layers.length > 1) {
            panes[1] = first.layers[1].id;
            layout = "curtain";
        }
    } else if (analyses.length > 1) {
        analyses.slice(0, PANE_COUNT).forEach((entry, pane) => {
            panes[pane] = entry.named ?? entry.layers[0]?.id ?? null;
        });
        layout = analyses.length === 2 ? "grid2" : "grid4";
    }
    return {
        layout,
        panes,
        active: 0,
        linkAll: false,
        filters: neutralFilters(),
        stack: { analysis: null, layers: [] },
        grouping: sharesFamily(maps) ? "tag" : "analysis",
    };
}

/** Fills the first `count` empty panes with canvases not placed yet: the analysis of the first placed pane first, then the others. */
function fill(
    panes: readonly (string | null)[],
    count: number,
    maps: readonly MapLine[],
): (string | null)[] {
    const filled = [...panes];
    const placed = new Set(filled.filter((pane) => pane !== null));
    const analyses = analysesOf(maps);
    const lead = filled.find((pane) => pane !== null);
    const leadAnalysis = lead ? analysisOf(lead, maps) : null;
    const ordered = [
        ...analyses.filter((entry) => entry.analysis === leadAnalysis),
        ...analyses.filter((entry) => entry.analysis !== leadAnalysis),
    ];
    const candidates = ordered
        .flatMap((entry) => entry.layers.map((layer) => layer.id))
        .filter((id) => !placed.has(id));
    for (let pane = 0; pane < count; pane++) {
        if (filled[pane] === null && candidates.length > 0) {
            filled[pane] = candidates.shift() as string;
        }
    }
    return filled;
}

/** Drops what the Selection no longer holds and fills the panes the layout shows. */
export function reconcile(
    state: TableState,
    maps: readonly MapLine[],
): TableState {
    const held = canvasesOf(maps);
    const panes = state.panes.map((pane) =>
        pane !== null && held.has(pane) ? pane : null,
    );
    const layers = state.stack.layers.filter((layer) => held.has(layer.canvas));
    const analyses = new Set(analysesOf(maps).map((entry) => entry.analysis));
    const stackKept =
        layers.length > 0 &&
        state.stack.analysis !== null &&
        analyses.has(state.stack.analysis);
    const next: TableState = {
        ...state,
        panes: fill(panes, PANES_SHOWN[state.layout], maps),
        stack: stackKept
            ? { analysis: state.stack.analysis, layers }
            : { analysis: null, layers: [] },
    };
    const same =
        next.panes.every((pane, index) => pane === state.panes[index]) &&
        next.stack.layers.length === state.stack.layers.length &&
        next.stack.analysis === state.stack.analysis;
    return same ? state : next;
}

function inPanes(pane: number): boolean {
    return Number.isInteger(pane) && pane >= 0 && pane < PANE_COUNT;
}

/** Lays `canvas` in `pane` (the target by default) and makes that pane the target. */
export function place(
    state: TableState,
    canvas: string,
    pane: number = state.active,
): TableState {
    if (!inPanes(pane)) return state;
    const panes = [...state.panes];
    panes[pane] = canvas;
    return { ...state, panes, active: pane };
}

/** The neighbouring layer of the same manifest, `step` away; the pane stays when there is none. */
export function stepPane(
    state: TableState,
    pane: number,
    step: 1 | -1,
    maps: readonly MapLine[],
): TableState {
    const canvas = inPanes(pane) ? state.panes[pane] : null;
    if (canvas === null) return state;
    const line = layerById(canvas, maps)?.line;
    if (!line) return state;
    const index = line.file.layers.findIndex((layer) => layer.id === canvas);
    const target = line.file.layers[index + step];
    return target ? place(state, target.id, pane) : state;
}

/** Exchanges the canvases of A and B; the filters stay with their pane. */
export function swap(state: TableState): TableState {
    const panes = [...state.panes];
    [panes[0], panes[1]] = [panes[1], panes[0]];
    return { ...state, panes };
}

export function setLayout(
    state: TableState,
    layout: TableLayout,
    maps: readonly MapLine[],
): TableState {
    return {
        ...state,
        layout,
        panes: fill(state.panes, PANES_SHOWN[layout], maps),
    };
}

export function setActive(state: TableState, pane: number): TableState {
    return inPanes(pane) ? { ...state, active: pane } : state;
}

export function setLinkAll(state: TableState, linkAll: boolean): TableState {
    return { ...state, linkAll };
}

export function setGrouping(
    state: TableState,
    grouping: TableGrouping,
): TableState {
    return { ...state, grouping };
}

/** Filters of pane `index` (the stack's at 4), the given fields over the current ones. */
export function setFilters(
    state: TableState,
    index: number,
    filters: Partial<PaneFilters>,
): TableState {
    if (!Number.isInteger(index) || index < 0 || index > PANE_COUNT) {
        return state;
    }
    const next = [...state.filters];
    next[index] = { ...next[index], ...filters };
    return { ...state, filters: next };
}

/** The filters of pane `index` for every pane; the stack's keep theirs. */
export function applyFiltersToAll(
    state: TableState,
    index: number,
): TableState {
    const source = state.filters[index];
    if (!source) return state;
    return {
        ...state,
        filters: state.filters.map((filters, at) =>
            at < PANE_COUNT ? { ...source } : filters,
        ),
    };
}

/** Whether `canvas` may join the stack: a layer of the stack's analysis, or of any when it is empty. */
export function canStack(
    state: { stack: { analysis: string | null } },
    canvas: string,
    maps: readonly MapLine[],
): boolean {
    const analysis = analysisOf(canvas, maps);
    if (analysis === null) return false;
    return state.stack.analysis === null || state.stack.analysis === analysis;
}

/** Adds the layer to the stack or takes it out; a layer of another analysis is refused (`canStack`) and the state returned as is. */
export function toggleInStack(
    state: TableState,
    canvas: string,
    maps: readonly MapLine[],
): TableState {
    if (state.stack.layers.some((layer) => layer.canvas === canvas)) {
        const layers = state.stack.layers.filter(
            (layer) => layer.canvas !== canvas,
        );
        return {
            ...state,
            stack: {
                analysis: layers.length > 0 ? state.stack.analysis : null,
                layers,
            },
        };
    }
    if (!canStack(state, canvas, maps)) return state;
    return {
        ...state,
        stack: {
            analysis: analysisOf(canvas, maps),
            layers: [
                ...state.stack.layers,
                { canvas, opacity: 100, on: true, tint: null },
            ],
        },
    };
}

function mapStack(
    state: TableState,
    canvas: string,
    change: (layer: StackLayer) => StackLayer,
): TableState {
    return {
        ...state,
        stack: {
            ...state.stack,
            layers: state.stack.layers.map((layer) =>
                layer.canvas === canvas ? change(layer) : layer,
            ),
        },
    };
}

/** Moves a stack layer one place; at an end the state is returned as is. */
export function moveInStack(
    state: TableState,
    canvas: string,
    step: 1 | -1,
): TableState {
    const layers = [...state.stack.layers];
    const from = layers.findIndex((layer) => layer.canvas === canvas);
    const to = from + step;
    if (from < 0 || to < 0 || to >= layers.length) return state;
    [layers[from], layers[to]] = [layers[to], layers[from]];
    return { ...state, stack: { ...state.stack, layers } };
}

/** Opacity in percent, whole, between 0 and 100. */
export function setOpacity(
    state: TableState,
    canvas: string,
    opacity: number,
): TableState {
    const value = Math.min(100, Math.max(0, Math.round(opacity)));
    return mapStack(state, canvas, (layer) => ({ ...layer, opacity: value }));
}

export function setVisible(
    state: TableState,
    canvas: string,
    on: boolean,
): TableState {
    return mapStack(state, canvas, (layer) => ({ ...layer, on }));
}

export function setTint(
    state: TableState,
    canvas: string,
    tint: string | null,
): TableState {
    return mapStack(state, canvas, (layer) => ({ ...layer, tint }));
}

/**
 * The layers of the other analyses that carry the family of `canvas`
 * (never a null family), analyses in slot order; empty without a mapping.
 */
export function pairsOf(canvas: string, maps: readonly MapLine[]): FileLayer[] {
    const here = layerById(canvas, maps);
    const family = here ? layerTag(here.layer)?.family : null;
    if (!here || !family) return [];
    return [...maps]
        .sort((a, b) => a.slot - b.slot)
        .filter((line) => line.analysis.id !== here.line.analysis.id)
        .flatMap((line) =>
            line.file.layers.filter(
                (layer) => layerTag(layer)?.family === family,
            ),
        );
}

/**
 * Panes whose zoom and pan follow each other, as lists of pane indexes: the
 * panes of one analysis, or every filled pane when `linkAll`. Only the grids
 * have synchronised maps; a single pane, a curtain and a stack draw one map.
 */
export function linkedGroups(
    state: TableState,
    maps: readonly MapLine[],
): number[][] {
    if (state.layout !== "grid2" && state.layout !== "grid4") return [];
    const groups = new Map<string, number[]>();
    for (let pane = 0; pane < PANES_SHOWN[state.layout]; pane++) {
        const canvas = state.panes[pane];
        if (canvas === null) continue;
        const analysis = state.linkAll ? "all" : analysisOf(canvas, maps);
        if (analysis === null) continue;
        groups.set(analysis, [...(groups.get(analysis) ?? []), pane]);
    }
    return [...groups.values()].filter((group) => group.length > 1);
}
