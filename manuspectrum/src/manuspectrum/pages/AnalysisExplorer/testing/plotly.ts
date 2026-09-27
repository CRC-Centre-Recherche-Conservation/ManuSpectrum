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
    Plots: {
        resize: vi.fn(async (_element: HTMLElement) => undefined),
    },
};

export function resetPlotly(): void {
    plotly.react.mockClear();
    plotly.relayout.mockClear();
    plotly.purge.mockClear();
    plotly.Plots.resize.mockClear();
}

export function plotlyModule(): { loadPlotly: () => Promise<typeof plotly> } {
    return { loadPlotly: async () => plotly };
}
