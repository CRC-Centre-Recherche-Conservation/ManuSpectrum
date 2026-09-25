import { validate as isUuid } from "uuid-esm";

import {
    emptyFilters,
    hasActiveFilters,
    LIST_FILTER_KEYS,
    PAGE_SIZES,
} from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { isViewAvailable } from "@/manuspectrum/pages/AnalysisExplorer/views/registry.ts";

import type { HistoryMode } from "@/manuspectrum/public/useUrlState.ts";
import type { EventType } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { ExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import type {
    CorpusScreen,
    DocumentState,
    ExplorerView,
    Filters,
    Focus,
    FolioView,
} from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";

export interface UrlSnapshot {
    view: ExplorerView;
    corpusScreen: CorpusScreen;
    document: DocumentState | null;
    focus: Focus | null;
    folioView: FolioView;
    filters: Filters;
}

const VIEWS: readonly ExplorerView[] = ["corpus", "map", "compare"];
const FOCUS_KINDS: readonly Focus["kind"][] = [
    "analysis",
    "characterization",
    "file",
    "sample",
];
const FOLIO_VIEWS: readonly FolioView[] = [
    "analyses",
    "characterizations",
    "samples",
];
const EVENT_TYPES: readonly EventType[] = [
    "production",
    "current-location",
    "modification",
    "alteration",
    "analysis",
    "sampling",
];
const YEAR = /^\d{1,4}$/;
const MAX_TEXT = 200;
const MAX_VALUE = 2048;
const MAX_VALUES = 50;

function uuidOrNull(raw: string | null): string | null {
    const value = (raw ?? "").trim().toLowerCase();
    return isUuid(value) ? value : null;
}

function listOf(query: URLSearchParams, key: string): string[] {
    const values = query
        .getAll(key)
        .flatMap((raw) => raw.split(","))
        .map((value) => value.trim())
        .filter((value) => value.length > 0 && value.length <= MAX_VALUE);
    return [...new Set(values)].sort().slice(0, MAX_VALUES);
}

function yearsOf(query: URLSearchParams): number[] {
    const years = listOf(query, "year")
        .filter((value) => YEAR.test(value))
        .map(Number);
    return [...new Set(years)].sort((a, b) => a - b);
}

function periodOf(raw: string | null): [number, number] | null {
    const match = /^(-?\d{1,4}),(-?\d{1,4})$/.exec((raw ?? "").trim());
    if (!match) {
        return null;
    }
    const start = Number(match[1]);
    const end = Number(match[2]);
    return start <= end ? [start, end] : null;
}

function focusOf(raw: string | null): Focus | null {
    const [kind, id] = (raw ?? "").split(":");
    const known = FOCUS_KINDS.find((candidate) => candidate === kind);
    const uuid = uuidOrNull(id ?? null);
    return known && uuid ? { kind: known, id: uuid } : null;
}

export function snapshotOf(store: ExplorerStore): UrlSnapshot {
    return JSON.parse(
        JSON.stringify({
            view: store.view,
            corpusScreen: store.corpusScreen,
            document: store.document,
            focus: store.focus,
            folioView: store.folioView,
            filters: store.filters,
        }),
    ) as UrlSnapshot;
}

export function toQuery(snapshot: UrlSnapshot): URLSearchParams {
    const { filters } = snapshot;
    const query = new URLSearchParams();
    if (snapshot.view !== "corpus") query.set("view", snapshot.view);
    if (snapshot.corpusScreen === "results") query.set("screen", "results");
    if (snapshot.document) {
        query.set("doc", snapshot.document.id);
        if (snapshot.document.canvas)
            query.set("canvas", snapshot.document.canvas);
    }
    if (snapshot.focus)
        query.set("focus", `${snapshot.focus.kind}:${snapshot.focus.id}`);
    if (snapshot.document && snapshot.folioView !== "analyses")
        query.set("fview", snapshot.folioView);
    if (filters.q) query.set("q", filters.q);
    if (filters.grain !== "documents") query.set("grain", filters.grain);
    if (filters.size !== PAGE_SIZES[0]) query.set("size", String(filters.size));
    if (filters.empty) query.set("empty", "1");
    for (const key of LIST_FILTER_KEYS) {
        for (const value of [...filters[key]].sort()) query.append(key, value);
    }
    for (const year of [...filters.year].sort((a, b) => a - b))
        query.append("year", String(year));
    if (filters.place) query.set("place", filters.place);
    if (filters.period)
        query.set("period", `${filters.period[0]},${filters.period[1]}`);
    for (const type of [...filters.eventType].sort())
        query.append("eventType", type);
    return query;
}

export function fromQuery(query: URLSearchParams): UrlSnapshot {
    const filters = emptyFilters();
    filters.q = (query.get("q") ?? "").trim().slice(0, MAX_TEXT);
    filters.grain =
        query.get("grain") === "analyses" ? "analyses" : "documents";
    filters.size =
        PAGE_SIZES.find((size) => String(size) === query.get("size")) ??
        PAGE_SIZES[0];
    filters.empty = ["1", "true", "yes"].includes(
        (query.get("empty") ?? "").toLowerCase(),
    );
    for (const key of LIST_FILTER_KEYS) {
        filters[key] = listOf(query, key);
    }
    filters.year = yearsOf(query);
    const place = (query.get("place") ?? "").trim();
    filters.place = place && place.length <= MAX_VALUE ? place : null;
    filters.period = periodOf(query.get("period"));
    filters.eventType = listOf(query, "eventType").filter(
        (type): type is EventType => EVENT_TYPES.includes(type as EventType),
    );

    const documentId = uuidOrNull(query.get("doc"));
    const canvas = (query.get("canvas") ?? "").trim();
    const document = documentId
        ? {
              id: documentId,
              canvas: canvas && canvas.length <= MAX_VALUE ? canvas : null,
          }
        : null;
    const requestedView = query.get("view");
    const view =
        VIEWS.find((candidate) => candidate === requestedView) ?? "corpus";
    const focus = documentId ? focusOf(query.get("focus")) : null;
    const requestedFolioView = query.get("fview");
    const folioView =
        FOLIO_VIEWS.find((candidate) => candidate === requestedFolioView) ??
        folioViewOf(focus);
    let corpusScreen: CorpusScreen = "home";
    if (document) {
        corpusScreen = "document";
    } else if (query.get("screen") === "results" || hasActiveFilters(filters)) {
        corpusScreen = "results";
    }
    return {
        view,
        corpusScreen,
        document,
        focus,
        folioView: document ? folioView : "analyses",
        filters,
    };
}

/** The folio view that shows a focused item: its own layer for an identified material or a sample. */
function folioViewOf(focus: Focus | null): FolioView {
    if (focus?.kind === "characterization") return "characterizations";
    if (focus?.kind === "sample") return "samples";
    return "analyses";
}

export function historyMode(
    previous: UrlSnapshot,
    next: UrlSnapshot,
): HistoryMode {
    if (JSON.stringify(previous) === JSON.stringify(next)) {
        return "none";
    }
    if (
        previous.view !== next.view ||
        previous.corpusScreen !== next.corpusScreen ||
        previous.document?.id !== next.document?.id
    ) {
        return "push";
    }
    if (previous.focus === null && next.focus !== null) {
        return "push";
    }
    return "replace";
}

/** Applies a URL snapshot; entering the document screen records the screen left as its origin. */
export function applySnapshot(
    store: ExplorerStore,
    snapshot: UrlSnapshot,
): void {
    store.$patch((state) => {
        state.view = isViewAvailable(snapshot.view) ? snapshot.view : "corpus";
        if (
            snapshot.corpusScreen === "document" &&
            state.corpusScreen !== "document"
        ) {
            state.documentOrigin = state.corpusScreen;
        }
        state.corpusScreen = snapshot.corpusScreen;
        state.document = snapshot.document;
        state.focus = snapshot.focus;
        state.folioView = snapshot.folioView;
        state.filters = snapshot.filters;
    });
}

export function documentHref(
    snapshot: UrlSnapshot,
    documentId: string,
): string {
    const query = toQuery({
        ...snapshot,
        corpusScreen: "document",
        document: { id: documentId, canvas: null },
        focus: null,
        folioView: "analyses",
    });
    return `?${query.toString()}`;
}
