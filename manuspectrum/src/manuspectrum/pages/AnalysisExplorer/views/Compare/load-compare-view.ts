import type { Component } from "vue";

/** The Compare view, in a chunk of its own (`explorer-compare`) fetched the first time it is shown. */
export async function loadCompareView(): Promise<Component> {
    const module = await import(
        /* webpackChunkName: "explorer-compare" */ "@/manuspectrum/pages/AnalysisExplorer/views/Compare/CompareView.vue"
    );
    return module.default;
}
