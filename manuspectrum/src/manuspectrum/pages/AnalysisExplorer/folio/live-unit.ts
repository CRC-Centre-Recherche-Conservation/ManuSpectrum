import { liveUnitOf } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";

import type { ZoneUnit } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { PageLayer } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";

/** The live unit a folio read, and the canvas it read it on. */
export interface LiveReport {
    canvas: string | null;
    unit: ZoneUnit | null;
}

/** The reported live unit when it is the one of `canvas`, else null. */
export function liveFor(
    canvas: string | null,
    reported: LiveReport | null,
): ZoneUnit | null {
    return canvas !== null && reported?.canvas === canvas
        ? reported.unit
        : null;
}

/** What two units that place zones alike share: their `x` and `y`. */
export function unitKey(unit: ZoneUnit | null): string {
    return unit ? `${unit.x}:${unit.y}` : "";
}

/**
 * Reports the live unit of `page`, laid for `canvas`, to `set` once its frame
 * is known, unless `isCurrent` says another page has replaced it by then. The
 * report names `canvas.id` as it was when the page was laid.
 */
export async function followLiveUnit(
    page: PageLayer,
    canvas: { id: string; width: number; height: number },
    isCurrent: () => boolean,
    set: (report: LiveReport) => void,
): Promise<void> {
    const id = canvas.id;
    const unit = await liveUnitOf(page, canvas);
    if (isCurrent()) set({ canvas: id, unit });
}
