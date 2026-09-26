import type { DocumentCanvas } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { DocumentView } from "@/manuspectrum/pages/AnalysisExplorer/folio/document-view.ts";

export interface PageCount {
    /** Analyses with a zone on the page, each counted once. */
    total: number;
    /** Those the Corpus filters keep. */
    matching: number;
    /** Identified materials and samples drawn on the page. */
    materials: number;
    samples: number;
}

function countOf(counts: Map<string, PageCount>, canvas: string): PageCount {
    let count = counts.get(canvas);
    if (!count) {
        count = { total: 0, matching: 0, materials: 0, samples: 0 };
        counts.set(canvas, count);
    }
    return count;
}

/** What each page of a document holds, by canvas id. */
export function pageCounts(
    payload: Pick<
        DocumentView,
        "annotations" | "characterizations" | "samples"
    >,
): Map<string, PageCount> {
    const counts = new Map<string, PageCount>();
    const seen = new Set<string>();
    for (const entry of payload.annotations) {
        const key = `${entry.canvas}\n${entry.analysis}`;
        if (seen.has(key)) continue;
        seen.add(key);
        const count = countOf(counts, entry.canvas);
        count.total += 1;
        if (entry.match) count.matching += 1;
    }
    for (const summary of payload.characterizations) {
        if (summary.zone) countOf(counts, summary.zone.canvas).materials += 1;
    }
    for (const entry of payload.samples) {
        if (entry.zone) countOf(counts, entry.zone.canvas).samples += 1;
    }
    return counts;
}

/** The first page, in the document's order, with an analysis the filters keep; null when none has one. */
export function firstMatchingPage(
    canvases: readonly DocumentCanvas[],
    counts: ReadonlyMap<string, PageCount>,
): string | null {
    return (
        canvases.find((canvas) => (counts.get(canvas.id)?.matching ?? 0) > 0)
            ?.id ?? null
    );
}
