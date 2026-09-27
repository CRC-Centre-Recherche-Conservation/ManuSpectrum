import { vi } from "vitest";

/**
 * The Plotly calls the Explorer makes, recorded, for specs:
 * `vi.mock("@/manuspectrum/pages/AnalysisExplorer/xy/plotly.ts", async () => (await import("…/testing/plotly.ts")).plotlyModule())`,
 * then assertions on `plotly` imported from this module.
 */
export const plotly = {
    react: vi.fn(
        async (
            _element: HTMLElement,
            _traces: unknown[],
            _layout: unknown,
            _config?: unknown,
        ) => undefined,
    ),
    relayout: vi.fn(
        async (_element: HTMLElement, _update: Record<string, unknown>) =>
            undefined,
    ),
    purge: vi.fn((_element: HTMLElement) => undefined),
    toImage: vi.fn(
        async (_figure: unknown, _options: unknown) =>
            "data:image/png;base64,AAAA",
    ),
    Plots: {
        resize: vi.fn(async (_element: HTMLElement) => undefined),
    },
};

/** The loader the mocked module answers with; a spec may delay or fail it. */
export const loadPlotly = vi.fn(async () => plotly);

export function resetPlotly(): void {
    loadPlotly.mockReset();
    loadPlotly.mockImplementation(async () => plotly);
    plotly.react.mockClear();
    plotly.relayout.mockClear();
    plotly.purge.mockClear();
    plotly.toImage.mockClear();
    plotly.Plots.resize.mockClear();
}

export function plotlyModule(): { loadPlotly: typeof loadPlotly } {
    return { loadPlotly };
}
