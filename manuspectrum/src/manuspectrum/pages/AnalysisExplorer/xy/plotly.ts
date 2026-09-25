type PlotlyModule = typeof import("plotly.js-cartesian-dist").default;

let loading: Promise<PlotlyModule> | null = null;

/** Plotly, loaded once for the card and (PR 5) Compare. */
export function loadPlotly(): Promise<PlotlyModule> {
    loading ??= import(
        /* webpackChunkName: "explorer-plotly" */ "plotly.js-cartesian-dist"
    ).then((module) => module.default);
    return loading;
}
