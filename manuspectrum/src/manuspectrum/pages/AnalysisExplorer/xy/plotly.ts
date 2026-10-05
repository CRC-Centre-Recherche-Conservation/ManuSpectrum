type PlotlyModule = typeof import("plotly.js-cartesian-dist").default;

let loading: Promise<PlotlyModule> | null = null;

/**
 * Plotly, loaded once for the card and Compare from the async `plotly` chunk
 * shared with the back office (webpack.project.js).
 */
export function loadPlotly(): Promise<PlotlyModule> {
    loading ??= import("plotly.js-cartesian-dist").then(
        (module) => module.default,
    );
    return loading;
}
