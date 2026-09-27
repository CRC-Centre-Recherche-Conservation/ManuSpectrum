/** Preset sizes of a Compare window: S, M, L. */
export type WindowSize = "S" | "M" | "L";

/**
 * One window of the Compare grid: a stable id (`auto:…`, `tool:<kind>:<params>`),
 * its title, its size when first placed. A window with `folded` set can be
 * folded to its header; `true` opens it folded.
 */
export interface CompareWindowSpec {
    id: string;
    title: string;
    size: WindowSize;
    folded?: boolean;
}

/** A window's place on the grid, in cells. */
export interface WindowBox {
    x: number;
    y: number;
    w: number;
    h: number;
}

/** Saved places, by window id. */
export type WindowLayout = Record<string, WindowBox>;
