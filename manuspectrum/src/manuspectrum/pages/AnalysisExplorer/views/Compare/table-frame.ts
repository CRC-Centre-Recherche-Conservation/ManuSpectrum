import { PANE_COUNT } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";

import type { TableLayout } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { WindowSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/types.ts";

/**
 * How the window holding the table is framed: its preset size (null once
 * resized by hand, read as M) and whether it is shown enlarged.
 */
export interface TableFrame {
    size: WindowSize | null;
    enlarged: boolean;
}

export type GalleryPlace = "right" | "below" | "hidden";

function isLarge(frame: TableFrame): boolean {
    return frame.enlarged || frame.size === "L";
}

/** The layout drawn: one pane in S, two instead of four in M. The stored layout is not changed. */
export function shownLayout(
    layout: TableLayout,
    frame: TableFrame,
): TableLayout {
    if (!frame.enlarged && frame.size === "S") return "single";
    if (layout === "grid4" && !isLarge(frame)) return "grid2";
    return layout;
}

/** Where the gallery is drawn: to the right in L and enlarged, below the table in M, nowhere in S or when closed. */
export function galleryPlace(frame: TableFrame, open: boolean): GalleryPlace {
    if (!open || (!frame.enlarged && frame.size === "S")) return "hidden";
    return isLarge(frame) ? "right" : "below";
}

/** Whether the gallery starts open in this frame: yes in L and enlarged, in M only for more analyses than panes. */
export function galleryOpensWith(frame: TableFrame, analyses: number): boolean {
    if (isLarge(frame)) return true;
    if (frame.size === "S") return false;
    return analyses > PANE_COUNT;
}
