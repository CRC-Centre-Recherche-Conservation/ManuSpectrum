import type { InjectionKey, Ref } from "vue";

import type {
    FileLayer,
    Label,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type { SelectionItems } from "@/manuspectrum/pages/AnalysisExplorer/composables/useSelectionItems.ts";
import type { WindowActionsHost } from "@/manuspectrum/pages/AnalysisExplorer/composables/useWindowActions.ts";
import type { Overlay } from "@/manuspectrum/pages/AnalysisExplorer/store/types.ts";
import type { TableState } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/light-table.ts";
import type { ServedSize } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/scale-notes.ts";
import type { TableFrame } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/table-frame.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

/** The last results shown (S1) and where the reader left them, to come back to them as they were. */
export interface ResultsMemo {
    /** The search query string of the page shown. */
    query: string;
    /** The filters it was reached with (query string at page 1), and its page. */
    filterKey: string;
    page: number;
    /** Number of results and grain of the page shown, for the way back from a document. */
    total: number;
    grain: "documents" | "analyses";
    /** Window scroll and id of the result opened, recorded when one is opened. */
    scroll: number;
    opened: string | null;
}

/** Labels of facet values seen in search payloads, keyed `${facetKey}:${valueId}`; filled by S1 and S0. */
export const FACET_LABELS_KEY: InjectionKey<Ref<Map<string, Label>>> =
    Symbol("facet-labels");

/** Set when the heading of the screen or view shown next should take the focus; cleared by the heading that takes it. */
export const SCREEN_FOCUS_KEY: InjectionKey<Ref<boolean>> =
    Symbol("screen-focus");

/** Key of the imaging overlay under the curtain (`overlayKey`), or null; provided by the document screen. */
export const CURTAIN_KEY: InjectionKey<Ref<string | null>> = Symbol("curtain");

/** Analyses that have a rectangle or polygon on the page shown: an imaging layer can be laid only there. */
export const FOLIO_ZONES_KEY: InjectionKey<Ref<ReadonlySet<string>>> =
    Symbol("folio-zones");

/** A folio asked of the folio image tools of Compare; `count` grows with each request, so the same folio asked again is a new one. */
export interface FolioRequest {
    canvas: string;
    count: number;
}

/** Where the folio image tools of Compare take the folio asked of them. */
export interface FolioRequests {
    asked: Readonly<Ref<FolioRequest | null>>;
    /** Asks every folio image tool to show `canvas`, named `label` in the announcement. */
    show: (canvas: string, label: string) => void;
}

export const FOLIO_REQUEST_KEY: InjectionKey<FolioRequests> =
    Symbol("folio-request");

/** Where an imaging preview keeps its laid layers (`overlayKey` → setting). */
export interface ImagingOverlays {
    settings: Readonly<Ref<Record<string, Overlay>>>;
    set(key: string, overlay: Overlay | null): void;
}

/** The laid layers of the imaging previews below; without it they are the document screen's (`store.overlays`). */
export const IMAGING_OVERLAYS_KEY: InjectionKey<ImagingOverlays> =
    Symbol("imaging-overlays");

/** Speaks a message through the shell's polite live region. */
export const ANNOUNCE_KEY: InjectionKey<(message: string) => void> =
    Symbol("announce");

/** The last results shown; provided by the shell, read back by S1 and by the way back from S2. */
export const RESULTS_MEMO_KEY: InjectionKey<Ref<ResultsMemo | null>> =
    Symbol("results-memo");

/** What a card knew of an item it added to the Selection, shown until the item is read. */
export interface SelectionHint {
    title: Label;
    /** The kind of item, translated (« spectrum », « map layer »…). */
    kind: string;
    /** A part of the title's item, such as a map layer's label. */
    detail?: string;
}

/** Hints of the items added to the Selection, by key; provided by the shell. */
export const SELECTION_HINTS_KEY: InjectionKey<
    Ref<Map<string, SelectionHint>>
> = Symbol("selection-hints");

/** Address of the Mirador viewer the IIIF products open in (`EXPLORER_MIRADOR_URL`); empty: no viewer. */
export const MIRADOR_URL_KEY: InjectionKey<string> = Symbol("mirador-url");

/** Counts, debounced, the size changes of the Compare grid and its windows; a window redraws what depends on its size (Plotly resize) when it changes. */
export const WINDOW_RESIZE_KEY: InjectionKey<Readonly<Ref<number>>> =
    Symbol("window-resize");

/** The one reading of the Selection's items, shared by the Selection panel and the Compare view; created on first call. Provided by the shell. */
export const SELECTION_ITEMS_KEY: InjectionKey<() => SelectionItems> =
    Symbol("selection-items");

/** The linked selection of the Compare view shown (`useLinkedSelection`); provided by the Compare view. */
export const LINKED_SELECTION_KEY: InjectionKey<LinkedSelection> =
    Symbol("linked-selection");

/** Where the body of a Compare window declares its actions, shown in the window's header (`useWindowActions`); provided by the window. */
export const WINDOW_ACTIONS_KEY: InjectionKey<WindowActionsHost> =
    Symbol("window-actions");

/** How the Compare window holding a body is framed (its preset size, enlarged or not); provided by the window. */
export const WINDOW_FRAME_KEY: InjectionKey<Readonly<Ref<TableFrame>>> =
    Symbol("window-frame");

/** What the light table lets its parts read; the table owns the state, the parts emit. */
export interface LightTableContext {
    state: Readonly<Ref<TableState>>;
    maps: Readonly<Ref<readonly MapLine[]>>;
    /** Every canvas of the Selection with its layer and map line. */
    byCanvas: Readonly<
        Ref<ReadonlyMap<string, { layer: FileLayer; line: MapLine }>>
    >;
    /** Sizes the panes were served at, by canvas; null while not read. */
    sizes: Readonly<Ref<ReadonlyMap<string, ServedSize | null>>>;
    /** Lays a canvas in a pane (the target by default). */
    place: (canvas: string, pane?: number) => void;
}

/** The state and actions of the light table shown; provided by `LightTable`. */
export const LIGHT_TABLE_KEY: InjectionKey<LightTableContext> =
    Symbol("light-table");
