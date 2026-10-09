import { loadPlotly } from "@/manuspectrum/pages/AnalysisExplorer/xy/plotly.ts";

import type { Component } from "vue";

import type {
    AnalysisPayload,
    DataKind,
    FileEntry,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

export type FolioMark = "point" | "frame";

export interface ExternalContext {
    file: FileEntry;
    analysis: AnalysisPayload;
    language: string;
    onEvent: (name: string, detail?: unknown) => void;
}

export interface ExternalHandle {
    destroy(): void;
    setState?(state: unknown): void;
}

/** Mount contract of a renderer built outside the Explorer (spec D49): RTI, multispectral. */
export type ExternalMount = (
    element: HTMLElement,
    context: ExternalContext,
) => ExternalHandle;

export interface ViewerEntry {
    kind: string;
    folio: FolioMark;
    preview: () => Promise<Component>;
    /** What the preview draws with besides its component (Plotly for spectra). */
    library: (() => Promise<unknown>) | null;
    external: ExternalMount | null;
}

const lazy = (load: () => Promise<{ default: Component }>) => () =>
    load().then((module) => module.default);

const BUILT_IN: Record<DataKind, ViewerEntry> = {
    xy: {
        kind: "xy",
        folio: "point",
        preview: lazy(
            () =>
                import(
                    "@/manuspectrum/pages/AnalysisExplorer/viewers/SpectrumPreview.vue"
                ),
        ),
        library: loadPlotly,
        external: null,
    },
    "chemical-imaging": {
        kind: "chemical-imaging",
        folio: "frame",
        preview: lazy(
            () =>
                import(
                    "@/manuspectrum/pages/AnalysisExplorer/viewers/ImagingPreview.vue"
                ),
        ),
        library: null,
        external: null,
    },
    "micro-imaging": {
        kind: "micro-imaging",
        folio: "frame",
        preview: lazy(
            () =>
                import(
                    "@/manuspectrum/pages/AnalysisExplorer/viewers/MicroImagePreview.vue"
                ),
        ),
        library: null,
        external: null,
    },
    file: {
        kind: "file",
        folio: "point",
        preview: lazy(
            () =>
                import(
                    "@/manuspectrum/pages/AnalysisExplorer/viewers/FileOnlyPreview.vue"
                ),
        ),
        library: null,
        external: null,
    },
};

const external = new Map<string, ViewerEntry>();

/**
 * How a data kind is drawn on the folio and previewed in the card. A kind the
 * Explorer does not know is a plain file (download only) until a renderer is
 * registered for it. An analysis whose only data is a file still has its place
 * on the folio: its mark is a point.
 */
export function viewerFor(kind: string): ViewerEntry {
    return external.get(kind) ?? BUILT_IN[kind as DataKind] ?? BUILT_IN.file;
}

export function registerExternalViewer(
    kind: string,
    mount: ExternalMount,
    folio: FolioMark = "frame",
): () => void {
    external.set(kind, {
        kind,
        folio,
        preview: lazy(
            () =>
                import(
                    "@/manuspectrum/pages/AnalysisExplorer/viewers/ExternalViewer.vue"
                ),
        ),
        library: null,
        external: mount,
    });
    return () => external.delete(kind);
}

/** The folio layer toggle that shows an analysis of this data kind: a frame is an imaging zone, a point a point analysis. */
export function folioLayerOf(kind: string): "points" | "zones" {
    return viewerFor(kind).folio === "frame" ? "zones" : "points";
}

/** Starts loading the preview of a data kind and its library before a card asks for them; a failure is left to the card. */
export function warmViewer(kind: string): void {
    const entry = viewerFor(kind);
    void Promise.all([entry.preview(), entry.library?.()]).catch(
        () => undefined,
    );
}
