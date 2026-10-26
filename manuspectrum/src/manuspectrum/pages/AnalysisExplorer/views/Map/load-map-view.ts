import type { Component } from "vue";

/** The Map & timeline view, in a chunk of its own (`explorer-map`, with MapLibre) fetched the first time it is shown. */
export async function loadMapView(): Promise<Component> {
    const module = await import(
        /* webpackChunkName: "explorer-map" */ "@/manuspectrum/pages/AnalysisExplorer/views/Map/MapView.vue"
    );
    return module.default;
}
