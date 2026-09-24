// declare untyped modules that have been added to your project in `package.json`
// Module homepage on npmjs.com uses logos "TS" or "DT" to indicate if typed

import("@/arches/declarations.d.ts");

declare module "plotly.js-cartesian-dist" {
    import * as Plotly from "plotly.js";
    export default Plotly;
}

declare module "utils/leaflet-stack" {
    import type { Layer, Map } from "leaflet";
    export function stackSmallestOnTop(
        map: Map,
        schedule?: (callback: () => void) => void,
        isPinned?: (layer: Layer) => boolean,
    ): void;
}
