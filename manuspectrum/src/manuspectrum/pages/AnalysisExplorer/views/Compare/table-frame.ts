import { PANE_COUNT } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

import type { TableLayout } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { WindowSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";

/**
 * How the window holding the table is framed: its preset size (null once
 * resized by hand) and whether it is shown enlarged.
 */
export interface TableFrame {
    size: WindowSize | null;
    enlarged: boolean;
    /** The screen is narrower than 48 rem. */
    phone: boolean;
}

export type GalleryPlace = "right" | "strip" | "hidden";

/** The width, in rem, the table keeps for itself before the gallery takes the rest. */
export const TABLE_MIN_REM = 40;
/** The width, in rem, of the gallery panel and of its rail. */
export const GALLERY_REM = 18.5;
export const RAIL_REM = 1.75;

/** The width, in rem, from which the gallery starts open beside the table. */
export const GALLERY_OPEN_REM = TABLE_MIN_REM + GALLERY_REM + RAIL_REM;

/** Layouts that put several panes side by side, which a phone cannot hold. */
export function isMultiPane(layout: TableLayout): boolean {
    return layout === "grid2" || layout === "grid4";
}

/**
 * The layout drawn: the selected one at any window size, except one pane in
 * S (its toolbar is disabled) and on a phone, where the two grids are not
 * offered (curtain and stack are kept). The stored layout is not changed.
 */
export function shownLayout(
    layout: TableLayout,
    frame: TableFrame,
): TableLayout {
    if (!frame.enlarged && frame.size === "S") return "single";
    if (frame.phone && isMultiPane(layout)) return "single";
    return layout;
}

/** Where the gallery is drawn: a strip under the table on a phone (not in S), a panel to the right of the table elsewhere, nowhere when closed. */
export function galleryPlace(frame: TableFrame, open: boolean): GalleryPlace {
    if (!open) return "hidden";
    if (frame.phone)
        return !frame.enlarged && frame.size === "S" ? "hidden" : "strip";
    return "right";
}

/**
 * Whether the gallery starts open when the reader has not chosen. Beside the
 * table (`width` in rem, null while unmeasured: the large and enlarged
 * windows): when the window holds the table and the gallery. On a phone, in
 * the strip: enlarged and large windows, in M only for more analyses than
 * panes.
 */
export function galleryOpensWith(
    frame: TableFrame,
    analyses: number,
    width: number | null = null,
): boolean {
    if (!frame.phone) {
        if (width !== null) return width >= GALLERY_OPEN_REM;
        return frame.enlarged || frame.size === "L";
    }
    if (frame.enlarged || frame.size === "L") return true;
    if (frame.size === "S") return false;
    return analyses > PANE_COUNT;
}
