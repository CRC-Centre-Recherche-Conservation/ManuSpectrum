import type { InjectionKey, Ref } from "vue";

import type {
    Label,
    SearchResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** The last results shown (S1) and where the reader left them, to come back to them as they were. */
export interface ResultsMemo {
    /** The search query string of the page shown. */
    query: string;
    /** The filters it was reached with (query string at page 1), and its page. */
    filterKey: string;
    page: number;
    payload: SearchResponse;
    /** Window scroll and id of the result opened, recorded when one is opened. */
    scroll: number;
    opened: string | null;
}

/** Labels of facet values seen in search payloads, keyed `${facetKey}:${valueId}`; filled by S1 and S0. */
export const FACET_LABELS_KEY: InjectionKey<Ref<Map<string, Label>>> =
    Symbol("facet-labels");

/** Set when the heading of the Corpus screen shown next should take the focus; cleared by the heading that takes it. */
export const SCREEN_FOCUS_KEY: InjectionKey<Ref<boolean>> =
    Symbol("screen-focus");

/** Key of the imaging overlay under the curtain (`overlayKey`), or null; provided by the document screen. */
export const CURTAIN_KEY: InjectionKey<Ref<string | null>> = Symbol("curtain");

/** Analyses that have a rectangle or polygon on the page shown: an imaging layer can be laid only there. */
export const FOLIO_ZONES_KEY: InjectionKey<Ref<ReadonlySet<string>>> =
    Symbol("folio-zones");

/** Speaks a message through the shell's polite live region. */
export const ANNOUNCE_KEY: InjectionKey<(message: string) => void> =
    Symbol("announce");

/** The last results shown; provided by the shell, read back by S1 and by the way back from S2. */
export const RESULTS_MEMO_KEY: InjectionKey<Ref<ResultsMemo | null>> =
    Symbol("results-memo");
