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

/** Places of the Compare windows on this browser; not synced between tabs. */
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

/** The boxes of a stored layout; anything else is dropped. */
export function parseLayout(raw: string | null): WindowLayout {
    if (raw === null) return {};
    let parsed: unknown;
    try {
        parsed = JSON.parse(raw);
    } catch {
        return {};
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed))
        return {};
    const layout: WindowLayout = {};
    for (const [id, value] of Object.entries(parsed)) {
        if (isBox(value)) {
            const { x, y, w, h } = value;
            layout[id] = { x, y, w, h };
        }
    }
    return layout;
}

export function readLayout(): WindowLayout {
    return parseLayout(readStorage(LAYOUT_STORAGE_KEY));
}

export function writeLayout(layout: WindowLayout): void {
    writeStorage(LAYOUT_STORAGE_KEY, JSON.stringify(layout));
}

export function clearLayout(): void {
    removeStorage(LAYOUT_STORAGE_KEY);
}

/** The places of the windows `ids` names. */
export function keepWindows(
    layout: WindowLayout,
    ids: readonly string[],
): WindowLayout {
    const kept: WindowLayout = {};
    for (const id of ids) {
        if (layout[id]) kept[id] = layout[id];
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
