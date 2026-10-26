import {
    readStorage,
    removeStorage,
    writeStorage,
} from "@/manuspectrum/public/safe-storage.ts";
import {
    NEUTRAL_FILTERS,
    PANE_COUNT,
    TABLE_LAYOUTS,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import { OFFERED_TOOLS } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/tools.ts";

import type {
    PaneFilters,
    StackLayer,
    StoredImaging,
    TableGrouping,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { ToolWindow } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";
import type {
    WindowBox,
    WindowLayout,
    WindowSize,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";

/** Places of the Compare windows, the windows hidden and those folded or unfolded by the reader, the tools open and the imaging light table, on this browser; not synced between tabs. */
export const LAYOUT_STORAGE_KEY = "ms-explorer-layout-v1";

export const GRID_COLUMNS = 12;

export const WINDOW_SIZES: Readonly<
    Record<WindowSize, Pick<WindowBox, "w" | "h">>
> = {
    S: { w: 4, h: 4 },
    M: { w: 6, h: 5 },
    L: { w: 12, h: 6 },
};

const SIZE_NAMES = Object.keys(WINDOW_SIZES) as WindowSize[];

function isCell(value: unknown, min: number, max: number): value is number {
    return (
        typeof value === "number" &&
        Number.isInteger(value) &&
        value >= min &&
        value <= max
    );
}

function isBox(value: unknown): value is WindowBox {
    if (typeof value !== "object" || value === null) return false;
    const box = value as Record<string, unknown>;
    return (
        isCell(box.x, 0, GRID_COLUMNS - 1) &&
        isCell(box.y, 0, Number.MAX_SAFE_INTEGER) &&
        isCell(box.w, 1, GRID_COLUMNS) &&
        isCell(box.h, 1, Number.MAX_SAFE_INTEGER)
    );
}

/**
 * The stored shape: the places of the windows (a folded window's box keeps
 * its unfolded height), the windows hidden, the windows the reader folded
 * (`true`) or unfolded (`false`), and the tools open (kind and parameters,
 * written only when one is open). `folded` and `tools` came after `hidden`
 * in the same version and may be absent. Version 3 adds `imaging`, the light
 * table (panes, stack, filters, grouping, linking, and `gallery` when the
 * reader showed or hid the gallery); a version 2 record has none.
 */
const LAYOUT_VERSION = 3;
const READABLE_VERSIONS: readonly number[] = [2, LAYOUT_VERSION];

export const XRF_DETECTORS = ["sdd", "si-pin"] as const;
export type XrfDetector = (typeof XRF_DETECTORS)[number];

/** The tube anodes an analysis can be given by hand. */
export const XRF_ANODES = [
    "Rh",
    "Ag",
    "W",
    "Mo",
    "Cr",
    "Cu",
    "Pd",
    "Ti",
    "Au",
    "Re",
] as const;
export type XrfAnode = (typeof XRF_ANODES)[number];

/** Most analyses and lens elements a stored record may hold; a longer one is dropped whole on read. */
export const XRF_MAX_ANODES = 200;
export const XRF_MAX_ELEMENTS = 30;

/** The XRF settings of the reader: the detector, the anode chosen per analysis (`none` = no tube line drawn) and the lens elements shared by every XRF window. */
export interface XrfSettings {
    detector: XrfDetector;
    anodes: Record<string, XrfAnode | "none">;
    elements: string[];
}

/** A tool open in Compare, as stored: its window id is derived from it (`toolWindowId`). */
export type StoredTool = Pick<ToolWindow, "kind" | "params">;

interface StoredLayout {
    boxes: WindowLayout;
    hidden: string[];
    folded: Record<string, boolean>;
    tools: StoredTool[];
    imaging: StoredImaging | undefined;
    xrf: XrfSettings | undefined;
}

function emptyLayout(): StoredLayout {
    return {
        boxes: {},
        hidden: [],
        folded: {},
        tools: [],
        imaging: undefined,
        xrf: undefined,
    };
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

function boxesOf(value: unknown): WindowLayout {
    const layout: WindowLayout = {};
    if (!isRecord(value)) return layout;
    for (const [id, entry] of Object.entries(value)) {
        if (isBox(entry)) {
            const { x, y, w, h } = entry;
            layout[id] = { x, y, w, h };
        }
    }
    return layout;
}

function hiddenOf(value: unknown): string[] {
    if (!Array.isArray(value)) return [];
    return [
        ...new Set(
            value.filter(
                (id): id is string => typeof id === "string" && id !== "",
            ),
        ),
    ];
}

function foldedOf(value: unknown): Record<string, boolean> {
    const folded: Record<string, boolean> = {};
    if (!isRecord(value)) return folded;
    for (const [id, state] of Object.entries(value)) {
        if (id !== "" && typeof state === "boolean") folded[id] = state;
    }
    return folded;
}

function isParams(value: unknown): value is Record<string, string> {
    return (
        isRecord(value) &&
        Object.values(value).every((entry) => typeof entry === "string")
    );
}

function toolsOf(value: unknown): StoredTool[] {
    if (!Array.isArray(value)) return [];
    return value.flatMap((entry) =>
        isRecord(entry) &&
        OFFERED_TOOLS.some((kind) => kind === entry.kind) &&
        isParams(entry.params)
            ? [
                  {
                      kind: entry.kind as StoredTool["kind"],
                      params: { ...entry.params },
                  },
              ]
            : [],
    );
}

function percentOf(value: unknown, fallback: number): number {
    return typeof value === "number" && Number.isFinite(value)
        ? Math.min(200, Math.max(0, Math.round(value)))
        : fallback;
}

function filtersOf(value: unknown): PaneFilters[] {
    const entries = Array.isArray(value) ? value : [];
    return Array.from({ length: PANE_COUNT + 1 }, (_, index) => {
        const entry: unknown = entries[index];
        if (!isRecord(entry)) return { ...NEUTRAL_FILTERS };
        return {
            brightness: percentOf(entry.brightness, NEUTRAL_FILTERS.brightness),
            contrast: percentOf(entry.contrast, NEUTRAL_FILTERS.contrast),
            saturation: percentOf(entry.saturation, NEUTRAL_FILTERS.saturation),
            greyscale: entry.greyscale === true,
        };
    });
}

function stackLayersOf(value: unknown): StackLayer[] {
    if (!Array.isArray(value)) return [];
    return value.flatMap((entry) =>
        isRecord(entry) && typeof entry.canvas === "string" && entry.canvas
            ? [
                  {
                      canvas: entry.canvas,
                      opacity: Math.min(100, percentOf(entry.opacity, 100)),
                      on: entry.on !== false,
                      tint: typeof entry.tint === "string" ? entry.tint : null,
                  },
              ]
            : [],
    );
}

/** The light table as stored, field by field: a field that is not readable takes its default; undefined when there is no record. */
function imagingOf(value: unknown): StoredImaging | undefined {
    if (!isRecord(value)) return undefined;
    const stack = isRecord(value.stack) ? value.stack : {};
    const layers = stackLayersOf(stack.layers);
    const panes = Array.isArray(value.panes) ? value.panes : [];
    const grouping: TableGrouping =
        value.grouping === "tag" ? "tag" : "analysis";
    return {
        layout:
            TABLE_LAYOUTS.find((layout) => layout === value.layout) ?? "single",
        panes: Array.from({ length: PANE_COUNT }, (_, index) => {
            const pane: unknown = panes[index];
            return typeof pane === "string" && pane !== "" ? pane : null;
        }),
        syncViews: value.syncViews === true,
        filters: filtersOf(value.filters),
        stack: {
            analysis:
                layers.length > 0 && typeof stack.analysis === "string"
                    ? stack.analysis
                    : null,
            layers,
        },
        grouping,
        ...(typeof value.gallery === "boolean"
            ? { gallery: value.gallery }
            : {}),
    };
}

/** The XRF settings as stored; undefined when the record is absent or malformed as a whole. */
function xrfOf(value: unknown): XrfSettings | undefined {
    if (!isRecord(value)) return undefined;
    const detector = XRF_DETECTORS.find((name) => name === value.detector);
    if (detector === undefined || !isRecord(value.anodes)) return undefined;
    if (!Array.isArray(value.elements)) return undefined;
    const entries = Object.entries(value.anodes);
    if (entries.length > XRF_MAX_ANODES) return undefined;
    const anodes: XrfSettings["anodes"] = {};
    for (const [id, anode] of entries) {
        const known = XRF_ANODES.find((name) => name === anode);
        if (id === "") return undefined;
        if (known !== undefined) anodes[id] = known;
        else if (anode === "none") anodes[id] = "none";
        else return undefined;
    }
    const elements = value.elements;
    if (
        elements.length > XRF_MAX_ELEMENTS ||
        !elements.every(
            (symbol) =>
                typeof symbol === "string" && /^[A-Z][a-z]?$/.test(symbol),
        ) ||
        new Set(elements).size !== elements.length
    ) {
        return undefined;
    }
    return { detector, anodes, elements: [...(elements as string[])] };
}

/**
 * A stored layout, anything unreadable dropped. A layout saved before hidden
 * windows existed is a bare `Record<windowId, box>`: its boxes are read, with
 * no window hidden.
 */
function parseStored(raw: string | null): StoredLayout {
    if (raw === null) return emptyLayout();
    let parsed: unknown;
    try {
        parsed = JSON.parse(raw);
    } catch {
        return emptyLayout();
    }
    if (!isRecord(parsed)) return emptyLayout();
    if (
        typeof parsed.version === "number" &&
        READABLE_VERSIONS.includes(parsed.version)
    ) {
        return {
            boxes: boxesOf(parsed.boxes),
            hidden: hiddenOf(parsed.hidden),
            folded: foldedOf(parsed.folded),
            tools: toolsOf(parsed.tools),
            imaging: imagingOf(parsed.imaging),
            xrf: xrfOf(parsed.xrf),
        };
    }
    return { ...emptyLayout(), boxes: boxesOf(parsed) };
}

function readStored(): StoredLayout {
    return parseStored(readStorage(LAYOUT_STORAGE_KEY));
}

function writeStored({
    boxes,
    hidden,
    folded,
    tools,
    imaging,
    xrf,
}: StoredLayout): void {
    writeStorage(
        LAYOUT_STORAGE_KEY,
        JSON.stringify({
            version: LAYOUT_VERSION,
            boxes,
            hidden,
            folded,
            ...(tools.length > 0 ? { tools } : {}),
            ...(imaging ? { imaging } : {}),
            ...(xrf ? { xrf } : {}),
        }),
    );
}

/** The boxes of a stored layout; anything else is dropped. */
export function parseLayout(raw: string | null): WindowLayout {
    return parseStored(raw).boxes;
}

export function readLayout(): WindowLayout {
    return readStored().boxes;
}

/** Saves the places of the windows; the rest stays as stored. */
export function writeLayout(layout: WindowLayout): void {
    writeStored({ ...readStored(), boxes: layout });
}

/** The windows arranged from the Selection that the reader hid, in the order hidden. */
export function readHidden(): string[] {
    return readStored().hidden;
}

/** Saves the hidden windows; the rest stays as stored. */
export function writeHidden(ids: readonly string[]): void {
    writeStored({ ...readStored(), hidden: [...ids] });
}

/** The windows the reader folded (`true`) or unfolded (`false`), by id. */
export function readFolded(): Record<string, boolean> {
    return readStored().folded;
}

/** Saves the windows the reader folded or unfolded; the rest stays as stored. */
export function writeFolded(folded: Readonly<Record<string, boolean>>): void {
    writeStored({ ...readStored(), folded: { ...folded } });
}

/** The tools open, in the order opened. */
export function readTools(): StoredTool[] {
    return readStored().tools;
}

/** Saves the tools open; the rest stays as stored. */
export function writeTools(tools: readonly StoredTool[]): void {
    writeStored({
        ...readStored(),
        tools: tools.map(({ kind, params }) => ({
            kind,
            params: { ...params },
        })),
    });
}

/** The light table as the reader left it; undefined when nothing was stored. */
export function readImaging(): StoredImaging | undefined {
    return readStored().imaging;
}

/** Saves the light table (undefined forgets it); the rest stays as stored. */
export function writeImaging(imaging: StoredImaging | undefined): void {
    const stored = { ...readStored(), imaging };
    if (isEmpty(stored)) removeStorage(LAYOUT_STORAGE_KEY);
    else writeStored(stored);
}

/** The XRF settings as the reader left them; undefined when nothing valid was stored. */
export function readXrfSettings(): XrfSettings | undefined {
    return readStored().xrf;
}

/** Saves the XRF settings (undefined forgets them); the rest stays as stored. */
export function writeXrfSettings(xrf: XrfSettings | undefined): void {
    const stored = {
        ...readStored(),
        xrf: xrf && {
            detector: xrf.detector,
            anodes: { ...xrf.anodes },
            elements: [...xrf.elements],
        },
    };
    if (isEmpty(stored)) removeStorage(LAYOUT_STORAGE_KEY);
    else writeStored(stored);
}

function isEmpty(stored: StoredLayout): boolean {
    return (
        Object.keys(stored.boxes).length === 0 &&
        stored.hidden.length === 0 &&
        Object.keys(stored.folded).length === 0 &&
        stored.tools.length === 0 &&
        stored.imaging === undefined &&
        stored.xrf === undefined
    );
}

/** Forgets the places of the windows; the hidden, folded and open windows and the light table stay as stored. */
export function clearBoxes(): void {
    const stored = { ...readStored(), boxes: {} };
    if (isEmpty(stored)) removeStorage(LAYOUT_STORAGE_KEY);
    else writeStored(stored);
}

/** Forgets the place, the hidden and the folded state of every window `ids` does not name; writes nothing when none is gone. */
export function forgetWindows(ids: readonly string[]): void {
    const stored = readStored();
    const boxes = keepWindows(stored.boxes, ids);
    const hidden = stored.hidden.filter((id) => ids.includes(id));
    const folded = keepWindows(stored.folded, ids);
    if (
        Object.keys(boxes).length === Object.keys(stored.boxes).length &&
        hidden.length === stored.hidden.length &&
        Object.keys(folded).length === Object.keys(stored.folded).length
    ) {
        return;
    }
    writeStored({ ...stored, boxes, hidden, folded });
}

/** The entries of the windows `ids` names. */
export function keepWindows<T>(
    layout: Readonly<Record<string, T>>,
    ids: readonly string[],
): Record<string, T> {
    const kept: Record<string, T> = {};
    for (const id of ids) {
        if (Object.prototype.hasOwnProperty.call(layout, id)) {
            kept[id] = layout[id];
        }
    }
    return kept;
}

/** Row by row, left to right: the order a reader and the keyboard follow. */
export function readingOrder<T extends { x: number; y: number }>(
    boxes: readonly T[],
): T[] {
    return [...boxes].sort((a, b) => a.y - b.y || a.x - b.x);
}

/** The gap between two spans on one axis, 0 when they touch or overlap. */
function gapBetween(
    start: number,
    length: number,
    otherStart: number,
    otherLength: number,
): number {
    return Math.max(
        0,
        otherStart - (start + length),
        start - (otherStart + otherLength),
    );
}

/**
 * The box nearest `target`, in grid cells: the smallest gap between their
 * edges, then the smallest distance between their centres, then the first
 * in reading order; null when there is none.
 */
export function nearestBox<T extends WindowBox>(
    target: WindowBox,
    boxes: readonly T[],
): T | null {
    const centreX = target.x + target.w / 2;
    const centreY = target.y + target.h / 2;
    let nearest: T | null = null;
    let nearestGap = Infinity;
    let nearestCentre = Infinity;
    for (const box of readingOrder(boxes)) {
        const gap =
            gapBetween(target.x, target.w, box.x, box.w) +
            gapBetween(target.y, target.h, box.y, box.h);
        const centre =
            Math.abs(box.x + box.w / 2 - centreX) +
            Math.abs(box.y + box.h / 2 - centreY);
        if (
            gap < nearestGap ||
            (gap === nearestGap && centre < nearestCentre)
        ) {
            nearest = box;
            nearestGap = gap;
            nearestCentre = centre;
        }
    }
    return nearest;
}

/**
 * Places windows in the order given, left to right, a new row below the
 * tallest window of the row when the next one does not fit. A window never
 * comes back up to a row above, so the order stays the reading order.
 */
export function flowLayout(
    windows: readonly { id: string; w: number; h: number }[],
    columns: number,
): WindowLayout {
    const layout: WindowLayout = {};
    let x = 0;
    let y = 0;
    let rowBottom = 0;
    for (const window of windows) {
        const w = Math.min(window.w, columns);
        if (x + w > columns) {
            x = 0;
            y = rowBottom;
        }
        layout[window.id] = { x, y, w, h: window.h };
        x += w;
        rowBottom = Math.max(rowBottom, y + window.h);
    }
    return layout;
}

/** The preset a box matches on a grid of `columns` (a preset is as wide as the grid at most), or null once it was resized by hand. */
export function sizeOf(
    box: Pick<WindowBox, "w" | "h">,
    columns: number = GRID_COLUMNS,
): WindowSize | null {
    return (
        SIZE_NAMES.find(
            (name) =>
                Math.min(WINDOW_SIZES[name].w, columns) === box.w &&
                WINDOW_SIZES[name].h === box.h,
        ) ?? null
    );
}
