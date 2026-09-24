import type { InjectionKey, Ref } from "vue";

import type { Label } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

/** Labels of facet values seen in search payloads, keyed `${facetKey}:${valueId}`; filled by S1 and S0. */
export const FACET_LABELS_KEY: InjectionKey<Ref<Map<string, Label>>> =
    Symbol("facet-labels");

/** Set when the heading of the Corpus screen shown next should take the focus; cleared by the heading that takes it. */
export const SCREEN_FOCUS_KEY: InjectionKey<Ref<boolean>> =
    Symbol("screen-focus");
