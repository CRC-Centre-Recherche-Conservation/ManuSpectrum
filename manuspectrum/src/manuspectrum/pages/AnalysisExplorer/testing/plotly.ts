import { vi } from "vitest";

type PlotlyHandler = (data: unknown) => void;

/** The handlers a chart bound with `element.on(name, handler)`, by element then event name. */
const handlers = new WeakMap<HTMLElement, Map<string, PlotlyHandler[]>>();

/** Gives `element` the `on` method Plotly adds to a chart it draws. */
function listen(element: HTMLElement): void {
    if (handlers.has(element)) return;
    const byName = new Map<string, PlotlyHandler[]>();
    handlers.set(element, byName);
    Object.assign(element, {
        on(name: string, handler: PlotlyHandler): void {
            byName.set(name, [...(byName.get(name) ?? []), handler]);
        },
    });
}

/** Runs the handlers `element` bound to the Plotly event `name`, as Plotly would. */
export function emitPlotly(
    element: Element,
    name: string,
    data: unknown,
): void {
    for (const handler of handlers.get(element as HTMLElement)?.get(name) ??
        []) {
        handler(data);
    }
}

/**
 * The Plotly calls the Explorer makes, recorded, for specs:
 * `vi.mock("@/manuspectrum/pages/AnalysisExplorer/xy/plotly.ts", async () => (await import("…/testing/plotly.ts")).plotlyModule())`,
 * then assertions on `plotly` imported from this module.
 */
export const plotly = {
    react: vi.fn(
        async (
            element: HTMLElement,
            _traces: unknown[],
            _layout: unknown,
            _config?: unknown,
        ) => {
            listen(element);
            return undefined;
        },
    ),
    restyle: vi.fn(
        async (
            _element: HTMLElement,
            _update: Record<string, unknown>,
            _traces?: number[],
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
    plotly.restyle.mockClear();
    plotly.relayout.mockClear();
    plotly.purge.mockClear();
    plotly.toImage.mockClear();
    plotly.Plots.resize.mockClear();
}

export function plotlyModule(): { loadPlotly: typeof loadPlotly } {
    return { loadPlotly };
}
