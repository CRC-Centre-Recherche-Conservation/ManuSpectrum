import {
    readStorage,
    removeStorage,
    writeStorage,
} from "@/manuspectrum/public/safe-storage.ts";

import type {
    WindowBox,
    WindowLayout,
    WindowSize,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";

/** Places of the Compare windows, the windows hidden and those folded or unfolded by the reader, on this browser; not synced between tabs. */
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
 * its unfolded height), the windows hidden, and the windows the reader
 * folded (`true`) or unfolded (`false`). `folded` came after `hidden` in the
 * same version and may be absent.
 */
const LAYOUT_VERSION = 2;

interface StoredLayout {
    boxes: WindowLayout;
    hidden: string[];
    folded: Record<string, boolean>;
}

function emptyLayout(): StoredLayout {
    return { boxes: {}, hidden: [], folded: {} };
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
    if (parsed.version === LAYOUT_VERSION) {
        return {
            boxes: boxesOf(parsed.boxes),
            hidden: hiddenOf(parsed.hidden),
            folded: foldedOf(parsed.folded),
        };
    }
    return { ...emptyLayout(), boxes: boxesOf(parsed) };
}

function readStored(): StoredLayout {
    return parseStored(readStorage(LAYOUT_STORAGE_KEY));
}

function writeStored({ boxes, hidden, folded }: StoredLayout): void {
    writeStorage(
        LAYOUT_STORAGE_KEY,
        JSON.stringify({ version: LAYOUT_VERSION, boxes, hidden, folded }),
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

/** Forgets the places, the hidden windows and the folded ones. */
export function clearLayout(): void {
    removeStorage(LAYOUT_STORAGE_KEY);
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
    writeStored({ boxes, hidden, folded });
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
