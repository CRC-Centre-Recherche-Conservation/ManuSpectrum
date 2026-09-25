import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import PrimeVue from "primevue/config";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import SpectrumPreview from "@/manuspectrum/pages/AnalysisExplorer/viewers/SpectrumPreview.vue";

import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisPayload,
    fileEntry,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { FileEntry } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

interface TraceCall {
    name: string;
    y: number[];
    line: { color: string };
}

interface LayoutCall {
    showlegend: boolean;
    xaxis: { title: { text: string } };
    yaxis: { title: { text: string } };
}

const plotly = vi.hoisted(() => ({
    react: vi.fn(
        async (
            _element: HTMLElement,
            _traces: TraceCall[],
            _layout: LayoutCall,
            _config?: unknown,
        ) => undefined,
    ),
    relayout: vi.fn(
        async (_element: HTMLElement, _update: Record<string, unknown>) =>
            undefined,
    ),
    purge: vi.fn((_element: HTMLElement) => undefined),
}));
vi.mock("@/manuspectrum/pages/AnalysisExplorer/xy/plotly.ts", () => ({
    loadPlotly: async () => plotly,
}));

const SERIES = {
    x: [1, 2, 3],
    y: [10, 30, 20],
    n_source: 3,
    decimated: false,
    x_reversed: false,
};

function readable(n: number, overrides: Partial<FileEntry> = {}): FileEntry {
    return fileEntry({
        id: uuid(700 + n),
        name: `P${n}.csv`,
        previewUrl: `http://testserver/api/spectrum-preview/${uuid(700 + n)}`,
        ...overrides,
    });
}

function mountPreview(files: FileEntry[], answers: (url: string) => Response) {
    vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string) => answers(url)),
    );
    const pinia = createPinia();
    setActivePinia(pinia);
    const analysis = analysisPayload({ files });
    const wrapper = mount(SpectrumPreview, {
        props: { file: files[0], analysis },
        global: { plugins: [pinia, PrimeVue] },
    });
    return { wrapper, store: useExplorerStore() };
}

function lastDrawing(): { traces: TraceCall[]; layout: LayoutCall } {
    const call = plotly.react.mock.calls.at(-1);
    if (!call) throw new Error("Plotly.react was not called");
    return { traces: call[1], layout: call[2] };
}

beforeEach(() => {
    document.documentElement.style.setProperty("--series-1", "#1d4ed8");
    document.documentElement.style.setProperty("--series-2", "#b45309");
    plotly.react.mockClear();
    plotly.relayout.mockClear();
    plotly.purge.mockClear();
});

afterEach(() => {
    vi.unstubAllGlobals();
    document.documentElement.removeAttribute("style");
});

describe("SpectrumPreview", () => {
    it("draws every readable file sharing the axes, one colour each, with a legend", async () => {
        const other = readable(3, {
            viewer: { ...fileEntry().viewer, axisKey: "other" },
        });
        const { wrapper } = mountPreview(
            [readable(1), readable(2), other],
            () => jsonResponse(SERIES),
        );
        await flushPromises();
        const { traces, layout } = lastDrawing();
        expect(traces.map((trace) => trace.name)).toEqual(["P1.csv", "P2.csv"]);
        expect(traces.map((trace) => trace.line.color)).toEqual([
            "#1d4ed8",
            "#b45309",
        ]);
        expect(layout.showlegend).toBe(true);
        expect(layout.xaxis.title.text).toBe("Energy (keV)");
        expect(layout.yaxis.title.text).toBe("Counts");
        wrapper.unmount();
    });

    it("draws a lone file without a legend", async () => {
        const { wrapper } = mountPreview([readable(1)], () =>
            jsonResponse(SERIES),
        );
        await flushPromises();
        const { traces, layout } = lastDrawing();
        expect(traces).toHaveLength(1);
        expect(layout.showlegend).toBe(false);
        wrapper.unmount();
    });

    it("names a file in the Selection by its A-label in the legend", async () => {
        const { wrapper, store } = mountPreview(
            [readable(1), readable(2)],
            () => jsonResponse(SERIES),
        );
        store.addToBasket(`af:${uuid(101)}:${uuid(702)}`);
        await flushPromises();
        const { traces } = lastDrawing();
        expect(traces[1].name).toBe("P2.csv (A1)");
        wrapper.unmount();
    });

    it("keeps drawing the other files when one fails, and says which", async () => {
        const { wrapper } = mountPreview([readable(1), readable(2)], (url) =>
            url.includes(uuid(702))
                ? jsonResponse({}, 503)
                : jsonResponse(SERIES),
        );
        await flushPromises();
        const { traces } = lastDrawing();
        expect(traces.map((trace) => trace.name)).toEqual(["P1.csv"]);
        expect(wrapper.text()).toContain("P2.csv could not be drawn.");
        wrapper.unmount();
    });

    it("says which file has nothing to draw", async () => {
        const { wrapper } = mountPreview(
            [readable(1)],
            () =>
                ({ ok: true, status: 204, json: async () => ({}) }) as Response,
        );
        await flushPromises();
        expect(wrapper.text()).toContain("P1.csv: nothing to draw.");
        expect(plotly.react).not.toHaveBeenCalled();
        wrapper.unmount();
    });

    it("says when a curve is a quick view of a larger file", async () => {
        const { wrapper } = mountPreview([readable(1)], () =>
            jsonResponse({ ...SERIES, n_source: 9000, decimated: true }),
        );
        await flushPromises();
        expect(wrapper.text()).toContain("9000");
        expect(wrapper.text()).toContain("workshop");
        wrapper.unmount();
    });

    it("stays a quick look: no processing, offset or export", async () => {
        const { wrapper } = mountPreview([readable(1), readable(2)], () =>
            jsonResponse(SERIES),
        );
        await flushPromises();
        expect(wrapper.find("input[type=radio]").exists()).toBe(false);
        expect(wrapper.find("button.offset").exists()).toBe(false);
        expect(wrapper.find("button.png").exists()).toBe(false);
        expect(wrapper.find("button.csv").exists()).toBe(false);
        wrapper.unmount();
    });

    it("puts a reversed x axis back on reset", async () => {
        const { wrapper } = mountPreview([readable(1)], () =>
            jsonResponse({ ...SERIES, x_reversed: true }),
        );
        await flushPromises();
        await wrapper.find("button.reset").trigger("click");
        expect(plotly.relayout).toHaveBeenCalledWith(expect.any(HTMLElement), {
            "xaxis.autorange": "reversed",
            "yaxis.autorange": true,
        });
        wrapper.unmount();
    });

    it("gives the points of one file to the table view", async () => {
        vi.stubGlobal(
            "ResizeObserver",
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            },
        );
        const { wrapper } = mountPreview([readable(1), readable(2)], () =>
            jsonResponse(SERIES),
        );
        await flushPromises();
        await wrapper.find("button.table-toggle").trigger("click");
        expect(
            wrapper.findComponent({ name: "DataTable" }).props("value"),
        ).toHaveLength(3);
        expect(
            wrapper.find("select.table-file").findAll("option"),
        ).toHaveLength(2);
        wrapper.unmount();
    });

    it("marks the English axis names of the table as English", async () => {
        vi.stubGlobal(
            "ResizeObserver",
            class {
                observe(): void {}
                unobserve(): void {}
                disconnect(): void {}
            },
        );
        const file = readable(1);
        file.viewer = {
            ...file.viewer,
            xLabel: "Wavelength (nm)",
            yLabel: "Reflectance",
        };
        const { wrapper } = mountPreview([file], () => jsonResponse(SERIES));
        await flushPromises();
        await wrapper.find("button.table-toggle").trigger("click");
        const names = wrapper
            .findAll('th [lang="en"]')
            .map((cell) => cell.text());
        expect(names).toEqual(["Wavelength (nm)", "Reflectance"]);
        wrapper.unmount();
    });
});
