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
    /** The screen is narrower than 48 rem. */
    phone: boolean;
}

export type GalleryPlace = "right" | "below" | "strip" | "hidden";

function isLarge(frame: TableFrame): boolean {
    return frame.enlarged || frame.size === "L";
}

/** The layout drawn: one pane in S and on a phone (curtain and stack kept), two instead of four in M. The stored layout is not changed. */
export function shownLayout(
    layout: TableLayout,
    frame: TableFrame,
): TableLayout {
    if (!frame.enlarged && frame.size === "S") return "single";
    if (frame.phone && (layout === "grid2" || layout === "grid4"))
        return "single";
    if (layout === "grid4" && !isLarge(frame)) return "grid2";
    return layout;
}

/** Where the gallery is drawn: a strip under the table on a phone, to the right in L and enlarged, below the table in M, nowhere in S or when closed. */
export function galleryPlace(frame: TableFrame, open: boolean): GalleryPlace {
    if (!open || (!frame.enlarged && frame.size === "S")) return "hidden";
    if (frame.phone) return "strip";
    return isLarge(frame) ? "right" : "below";
}

/** Whether the gallery starts open in this frame: yes in L and enlarged, in M only for more analyses than panes. */
export function galleryOpensWith(frame: TableFrame, analyses: number): boolean {
    if (isLarge(frame)) return true;
    if (frame.size === "S") return false;
    return analyses > PANE_COUNT;
}
