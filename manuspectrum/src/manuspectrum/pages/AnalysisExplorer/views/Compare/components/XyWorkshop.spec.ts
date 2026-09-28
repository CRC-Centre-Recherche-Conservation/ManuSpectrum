import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { ref } from "vue";

import XyWorkshop from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/XyWorkshop.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { WINDOW_RESIZE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    analysisHit,
    fileEntry,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    loadPlotly,
    plotly,
    resetPlotly,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/plotly.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { VueWrapper } from "@vue/test-utils";
import type {
    FileViewer,
    Series,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { FileLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

vi.mock("@/manuspectrum/pages/AnalysisExplorer/xy/plotly.ts", async () =>
    (
        await import("@/manuspectrum/pages/AnalysisExplorer/testing/plotly.ts")
    ).plotlyModule(),
);

interface TraceCall {
    name: string;
    x: number[];
    y: number[];
    customdata?: number[];
    xaxis?: string;
    mode: string;
    line: { color: string; dash: string };
    marker: {
        symbol: string;
        color: string;
        maxdisplayed: number;
        line: { color: string };
    };
    legendgroup: string;
    legendgrouptitle: { text: string };
}

interface LayoutCall {
    showlegend: boolean;
    paper_bgcolor: string;
    grid?: { rows: number; columns: number };
    annotations: { text: string }[];
    legend: { groupclick: string };
    xaxis: { title: { text: string }; autorange: unknown };
    yaxis: { title: { text: string } };
    [axis: string]: unknown;
}

const INK = "#1a1a2e";
const BACKGROUND = "#faf9f7";
const COLOURS = [
    "#1d4ed8",
    "#b45309",
    "#6d28d9",
    "#047857",
    "#b91c1c",
    "#0891b2",
    "#a16207",
    "#be185d",
];

function series(x: number[], y: number[], xReversed = false): Series {
    return {
        x,
        y,
        n_source: x.length,
        decimated: false,
        x_reversed: xReversed,
    };
}

const SERIES = series([1, 2, 3], [10, 30, 20]);

function curve(
    slot: number,
    n: number,
    viewer: Partial<FileViewer> = {},
): FileLine {
    const analysis = analysisHit(slot + 1);
    const file = fileEntry({
        id: uuid(700 + n),
        name: `S${n}.csv`,
        previewUrl: `http://testserver/api/spectrum-preview/${uuid(700 + n)}`,
        viewer: { ...fileEntry().viewer, ...viewer },
    });
    return { key: `an:${analysis.id}:-`, slot, analysis, file };
}

let fetchMock: ReturnType<typeof vi.fn>;
let wrapper: VueWrapper | null = null;
let answers: Map<string, Response>;

/** Answers each preview by its file number `n`; the others get `SERIES`. */
function answer(n: number, response: Response): void {
    answers.set(`/api/spectrum-preview/${uuid(700 + n)}?n=full`, response);
}

async function mountWorkshop(
    curves: FileLine[],
    resize = ref(0),
): Promise<VueWrapper> {
    wrapper = mount(XyWorkshop, {
        attachTo: document.body,
        props: { curves },
        global: { provide: { [WINDOW_RESIZE_KEY as symbol]: resize } },
    });
    await flushPromises();
    return wrapper;
}

function lastDrawing(): { traces: TraceCall[]; layout: LayoutCall } {
    const call = plotly.react.mock.calls.at(-1);
    if (!call) throw new Error("Plotly.react was not called");
    return { traces: call[1] as TraceCall[], layout: call[2] as LayoutCall };
}

function readBlob(blob: Blob): Promise<string> {
    return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.readAsText(blob);
    });
}

function readBytes(blob: Blob): Promise<ArrayBuffer> {
    return new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result as ArrayBuffer);
        reader.readAsArrayBuffer(blob);
    });
}

function notes(view: VueWrapper): string[] {
    return view.findAll(".notes li").map((item) => item.text());
}

beforeEach(() => {
    forgetPayloads();
    resetPlotly();
    COLOURS.forEach((colour, index) =>
        document.documentElement.style.setProperty(
            `--series-${index + 1}`,
            colour,
        ),
    );
    document.documentElement.style.setProperty("--ink", INK);
    document.documentElement.style.setProperty("--bg", BACKGROUND);
    answers = new Map();
    fetchMock = vi.fn(
        async (url: string) => answers.get(url) ?? jsonResponse(SERIES),
    );
    vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    document.documentElement.removeAttribute("style");
});

describe("XyWorkshop", () => {
    it("asks every point of each readable file", async () => {
        await mountWorkshop([curve(0, 1), curve(1, 2)]);
        expect(fetchMock.mock.calls.map(([url]) => url)).toEqual([
            `/api/spectrum-preview/${uuid(701)}?n=full`,
            `/api/spectrum-preview/${uuid(702)}?n=full`,
        ]);
    });

    it("draws each file in its slot colour, a slot's next files dashed, named « A1 · file »", async () => {
        await mountWorkshop([curve(0, 1), curve(0, 2), curve(1, 3)]);
        const { traces, layout } = lastDrawing();
        expect(traces.map((trace) => trace.name)).toEqual([
            "A1 · S1.csv",
            "A1 · S2.csv",
            "A2 · S3.csv",
        ]);
        expect(traces.map((trace) => trace.line.color)).toEqual([
            COLOURS[0],
            COLOURS[0],
            COLOURS[1],
        ]);
        expect(traces.map((trace) => trace.line.dash)).toEqual([
            "solid",
            "dash",
            "solid",
        ]);
        expect(layout.showlegend).toBe(true);
        expect(layout.xaxis.title.text).toBe("Energy (keV)");
        expect(layout.yaxis.title.text).toBe("Counts");
    });

    it("marks each slot with a marker shape of its own and groups its files in the legend, a few markers per curve", async () => {
        const view = await mountWorkshop([
            curve(0, 1),
            curve(0, 2),
            curve(1, 3),
            curve(9, 4),
        ]);
        const { traces, layout } = lastDrawing();
        expect(traces.map((trace) => trace.mode)).toEqual(
            Array(4).fill("lines+markers"),
        );
        expect(traces.map((trace) => trace.marker.symbol)).toEqual([
            "circle",
            "circle",
            "square",
            "hexagon",
        ]);
        expect(traces.map((trace) => trace.marker.color)).toEqual([
            COLOURS[0],
            COLOURS[0],
            COLOURS[1],
            INK,
        ]);
        expect(traces[3].marker.line.color).toBe(INK);
        expect(
            traces.every(
                (trace) =>
                    trace.marker.maxdisplayed > 0 &&
                    trace.marker.maxdisplayed <= 20,
            ),
        ).toBe(true);
        expect(traces.map((trace) => trace.legendgroup)).toEqual([
            "slot-0",
            "slot-0",
            "slot-1",
            "slot-9",
        ]);
        expect(traces.map((trace) => trace.legendgrouptitle.text)).toEqual([
            "A1",
            "A1",
            "A2",
            "A10",
        ]);
        expect(layout.legend.groupclick).toBe("toggleitem");

        await view.find('[data-layout="multiples"]').trigger("click");
        await flushPromises();
        expect(
            lastDrawing().traces.map((trace) => trace.marker.symbol),
        ).toEqual(["circle", "circle", "square", "hexagon"]);
    });

    it("titles the axes from the first drawn spectrum that stores a title", async () => {
        await mountWorkshop([
            curve(0, 1, { xLabel: null, yLabel: null }),
            curve(1, 2, { xLabel: "Energy (eV)", yLabel: "Net counts" }),
        ]);
        const { layout } = lastDrawing();
        expect(layout.xaxis.title.text).toBe("Energy (eV)");
        expect(layout.yaxis.title.text).toBe("Net counts");
    });

    it("skips a stored title that holds only spaces", async () => {
        await mountWorkshop([
            curve(0, 1, { xLabel: " ", yLabel: "  " }),
            curve(1, 2, { xLabel: "Energy (eV) ", yLabel: "Net counts" }),
        ]);
        const { layout } = lastDrawing();
        expect(layout.xaxis.title.text).toBe("Energy (eV)");
        expect(layout.yaxis.title.text).toBe("Net counts");
    });

    it("names a file too large to draw in full and one with nothing to draw, and draws the others", async () => {
        answer(1, jsonResponse({}, 413));
        answer(2, {
            ok: true,
            status: 204,
            json: async () => ({}),
        } as Response);
        const view = await mountWorkshop([
            curve(0, 1),
            curve(1, 2),
            curve(2, 3),
        ]);
        expect(lastDrawing().traces.map((trace) => trace.name)).toEqual([
            "A3 · S3.csv",
        ]);
        expect(notes(view)).toEqual([
            "A1 · S1.csv: too large to draw in full; download the file to read it.",
            "A2 · S2.csv: nothing to draw.",
        ]);
        expect(view.find(".retry").exists()).toBe(false);
    });

    it("offers a retry when a file fails on a server error", async () => {
        answer(1, jsonResponse({}, 503));
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        expect(notes(view)).toEqual(["A1 · S1.csv could not be drawn."]);
        answers.clear();
        await view.find(".retry").trigger("click");
        await flushPromises();
        expect(lastDrawing().traces).toHaveLength(2);
    });

    it("lifts each offset curve by a step, keeping the real values for the hover and the Y title", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await view.find('[data-layout="offset"]').trigger("click");
        await flushPromises();
        const { traces, layout } = lastDrawing();
        expect(traces[0].y).toEqual([10, 30, 20]);
        expect(traces[1].y).toEqual([32, 52, 42]);
        expect(traces[1].customdata).toEqual([10, 30, 20]);
        expect(layout.yaxis.title.text).toBe("Counts");
        expect(
            view.find('[data-layout="offset"]').attributes("aria-pressed"),
        ).toBe("true");
    });

    it("lifts an offset curve above the whole curve below it, whatever their ranges", async () => {
        answer(1, jsonResponse(series([1, 2, 3], [100, 120, 110])));
        answer(3, jsonResponse(series([1, 2, 3], [-5, 0, 5])));
        const view = await mountWorkshop([
            curve(0, 1),
            curve(1, 2),
            curve(2, 3),
        ]);
        await view.find('[data-layout="offset"]').trigger("click");
        await flushPromises();
        const { traces } = lastDrawing();
        for (let index = 1; index < traces.length; index += 1) {
            expect(Math.min(...traces[index].y)).toBeGreaterThan(
                Math.max(...traces[index - 1].y),
            );
        }
        expect(traces[2].customdata).toEqual([-5, 0, 5]);
    });

    it("opens on small multiples above eight curves, one panel per slot, and goes back to overlay", async () => {
        const curves = Array.from({ length: 9 }, (_, index) =>
            curve(index, index + 1),
        );
        const view = await mountWorkshop(curves);
        const { traces, layout } = lastDrawing();
        expect(layout.grid).toMatchObject({ rows: 3, columns: 3 });
        expect(traces.map((trace) => trace.xaxis)).toEqual([
            "x",
            "x2",
            "x3",
            "x4",
            "x5",
            "x6",
            "x7",
            "x8",
            "x9",
        ]);
        expect(layout.annotations.map((note) => note.text)).toEqual(
            curves.map((_, index) => `A${index + 1}`),
        );
        expect(traces[8].line.color).toBe(INK);

        await view.find('[data-layout="overlay"]').trigger("click");
        await flushPromises();
        const overlay = lastDrawing();
        expect(overlay.layout.grid).toBeUndefined();
        expect(overlay.layout.annotations.map((note) => note.text)).toEqual([
            "A9",
        ]);
    });

    it("overlays eight curves", async () => {
        await mountWorkshop(
            Array.from({ length: 8 }, (_, index) => curve(index, index + 1)),
        );
        expect(lastDrawing().layout.grid).toBeUndefined();
    });

    it("offers the treatments of the preset, and runs the chosen one on every curve, named in the Y title", async () => {
        answer(2, jsonResponse(series([1, 2, 3], [-40, 20, 10])));
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        const options = view.findAll("select option");
        expect(options.map((option) => option.attributes("value"))).toEqual([
            "base",
            "normalize-max",
        ]);
        expect(options.map((option) => option.text())).toEqual([
            "As measured",
            "Normalised to maximum",
        ]);
        await view.find("select").setValue("normalize-max");
        await flushPromises();
        const { traces, layout } = lastDrawing();
        expect(traces[0].y).toEqual([1 / 3, 1, 2 / 3]);
        expect(traces[1].y).toEqual([-1, 0.5, 0.25]);
        expect(layout.yaxis.title.text).toBe("Counts [normalised to maximum]");
    });

    it("names a treatment in the Y title with the words of its menu entry", async () => {
        const view = await mountWorkshop([
            curve(0, 1, { presetKey: "mass_spec" }),
        ]);
        const option = view.find('select option[value="normalize-area"]');
        expect(option.text()).toBe("Normalised to total (TIC)");
        await view.find("select").setValue("normalize-area");
        await flushPromises();
        expect(lastDrawing().layout.yaxis.title.text).toBe(
            "Counts [normalised to total (TIC)]",
        );
    });

    it("offers only the treatments shared by different presets, and says so", async () => {
        const view = await mountWorkshop([
            curve(0, 1, { presetKey: "fors" }),
            curve(1, 2, { presetKey: "ftir_reflection" }),
        ]);
        expect(
            view
                .findAll("select option")
                .map((option) => option.attributes("value")),
        ).toEqual(["base", "log-inverse-r", "kubelka-munk"]);
        expect(view.find(".mixed").text()).toBe(
            "These spectra come from different configurations: only the treatments they share are offered.",
        );
    });

    it("offers no treatment menu for a preset without views", async () => {
        const view = await mountWorkshop([curve(0, 1, { presetKey: null })]);
        expect(view.find("select").exists()).toBe(false);
        expect(view.find(".mixed").exists()).toBe(false);
    });

    it("flags a curve out of the shared X range", async () => {
        answer(3, jsonResponse(series([100, 200], [1, 2])));
        const view = await mountWorkshop([
            curve(0, 1),
            curve(1, 2),
            curve(2, 3),
        ]);
        expect(notes(view)).toEqual([
            "A3 · S3.csv: out of the shared X range.",
        ]);
        await view.find('[data-layout="table"]').trigger("click");
        expect(view.findAll(".xy-curve-list .flag")).toHaveLength(1);
    });

    it("notes that intensities are not comparable across instruments", async () => {
        const view = await mountWorkshop([curve(0, 1)]);
        expect(view.text()).toContain(
            "Intensities are not comparable in absolute value across instruments.",
        );
    });

    it("keeps a reversed X axis reversed on reset", async () => {
        answers.set(
            `/api/spectrum-preview/${uuid(701)}?n=full`,
            jsonResponse(series([3, 2, 1], [1, 2, 3], true)),
        );
        const view = await mountWorkshop([curve(0, 1)]);
        expect(lastDrawing().layout.xaxis.autorange).toBe("reversed");
        await view.find('[data-action="reset"]').trigger("click");
        await flushPromises();
        expect(plotly.relayout).toHaveBeenCalledWith(expect.any(HTMLElement), {
            "xaxis.autorange": "reversed",
            "yaxis.autorange": true,
        });
    });

    it("exports the PNG on the page background", async () => {
        const click = vi
            .spyOn(HTMLAnchorElement.prototype, "click")
            .mockImplementation(() => undefined);
        const view = await mountWorkshop([curve(0, 1)]);
        await view.find('[data-action="png"]').trigger("click");
        await flushPromises();
        const [figure, options] = plotly.toImage.mock.calls[0] as [
            { layout: LayoutCall },
            { format: string },
        ];
        expect(figure.layout.paper_bgcolor).toBe(BACKGROUND);
        expect(figure.layout.plot_bgcolor).toBe(BACKGROUND);
        expect(options.format).toBe("png");
        expect(click).toHaveBeenCalledTimes(1);
    });

    it("exports the treated values without the offset as CSV, one column pair per curve, marked UTF-8", async () => {
        vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
            () => undefined,
        );
        const blobs: Blob[] = [];
        Object.assign(URL, {
            createObjectURL: (blob: Blob) => {
                blobs.push(blob);
                return "blob:csv";
            },
            revokeObjectURL: () => undefined,
        });
        answer(2, jsonResponse(series([4, 5, 6], [5, 10, 20])));
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await view.find('[data-layout="offset"]').trigger("click");
        await view.find("select").setValue("normalize-max");
        await view.find('[data-action="csv"]').trigger("click");
        expect([
            ...new Uint8Array(await readBytes(blobs[0])).slice(0, 3),
        ]).toEqual([0xef, 0xbb, 0xbf]);
        expect((await readBlob(blobs[0])).split("\r\n")).toEqual([
            "A1 · S1.csv · Energy (keV),A1 · S1.csv · Counts [normalised to maximum]," +
                "A2 · S2.csv · Energy (keV),A2 · S2.csv · Counts [normalised to maximum]",
            `1,${1 / 3},4,0.25`,
            "2,1,5,0.5",
            `3,${2 / 3},6,1`,
            "",
        ]);
    });

    it("lists the curves in the table layout, without a chart", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        plotly.react.mockClear();
        await view.find('[data-layout="table"]').trigger("click");
        await flushPromises();
        expect(view.find(".chart").exists()).toBe(false);
        expect(
            view.findAll(".xy-curve-list tbody th").map((cell) => cell.text()),
        ).toEqual(["A1 · S1.csv", "A2 · S2.csv"]);
        expect(view.find(".xy-curve-list tbody td.number").text()).toBe("3");
        expect(plotly.react).not.toHaveBeenCalled();
    });

    it("groups the chart tools, each reached with Tab", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        const tools = view.find(".toolbar");
        expect(tools.attributes("role")).toBe("group");
        expect(tools.attributes("aria-label")).toBe("Chart tools");
        expect(
            tools
                .findAll("button")
                .every((button) => !button.attributes("tabindex")),
        ).toBe(true);
    });

    it("purges the chart it leaves for the table layout", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        const element = view.find(".chart").element;
        await view.find('[data-layout="table"]').trigger("click");
        await flushPromises();
        expect(plotly.purge).toHaveBeenCalledWith(element);
    });

    it("resizes the chart only when its size changed, and purges it on unmount", async () => {
        const resize = ref(0);
        const view = await mountWorkshop([curve(0, 1)], resize);
        resize.value += 1;
        await flushPromises();
        expect(plotly.Plots.resize).not.toHaveBeenCalled();
        const element = view.find(".chart").element;
        Object.defineProperty(element, "clientWidth", { value: 640 });
        resize.value += 1;
        await flushPromises();
        expect(plotly.Plots.resize).toHaveBeenCalledTimes(1);
        resize.value += 1;
        await flushPromises();
        expect(plotly.Plots.resize).toHaveBeenCalledTimes(1);
        view.unmount();
        wrapper = null;
        expect(plotly.purge).toHaveBeenCalledWith(element);
    });

    it("aborts the requests of an unmounted window", async () => {
        const signals: AbortSignal[] = [];
        fetchMock.mockImplementation(
            (_url: string, init: RequestInit) =>
                new Promise<Response>(() => {
                    signals.push(init.signal as AbortSignal);
                }),
        );
        const view = await mountWorkshop([curve(0, 1)]);
        view.unmount();
        wrapper = null;
        expect(signals[0].aborted).toBe(true);
    });

    it("draws nothing once its window is gone before Plotly arrives", async () => {
        const waiting: ((module: typeof plotly) => void)[] = [];
        loadPlotly.mockImplementation(
            () => new Promise((resolve) => waiting.push(resolve)),
        );
        const view = await mountWorkshop([curve(0, 1)]);
        expect(waiting.length).toBeGreaterThan(0);
        view.unmount();
        wrapper = null;
        waiting.forEach((resolve) => resolve(plotly));
        await flushPromises();
        expect(plotly.react).not.toHaveBeenCalled();
    });

    it("purges a chart whose drawing ends after its window is gone", async () => {
        let drawn: () => void = () => undefined;
        plotly.react.mockImplementationOnce(
            () =>
                new Promise<undefined>(
                    (resolve) => (drawn = () => resolve(undefined)),
                ),
        );
        const view = await mountWorkshop([curve(0, 1)]);
        const element = view.find(".chart").element;
        view.unmount();
        wrapper = null;
        plotly.purge.mockClear();
        drawn();
        await flushPromises();
        expect(plotly.purge).toHaveBeenCalledWith(element);
    });

    it("says so in the window when the chart cannot be drawn", async () => {
        vi.spyOn(console, "error").mockImplementation(() => undefined);
        loadPlotly.mockImplementation(async () => {
            throw new Error("offline");
        });
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        expect(view.find(".draw-failed").text()).toBe(
            "The chart could not be drawn.",
        );
    });

    it("names one spectrum in the chart's label", async () => {
        const view = await mountWorkshop([curve(0, 1)]);
        expect(view.find(".chart").attributes("aria-label")).toBe(
            "Chart of 1 spectrum; the Table layout lists its range.",
        );
    });

    it("frees the CSV once the browser has taken it", async () => {
        vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
            () => undefined,
        );
        const revoke = vi.fn();
        Object.assign(URL, {
            createObjectURL: () => "blob:csv",
            revokeObjectURL: revoke,
        });
        const view = await mountWorkshop([curve(0, 1)]);
        await view.find('[data-action="csv"]').trigger("click");
        expect(revoke).not.toHaveBeenCalled();
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(revoke).toHaveBeenCalledWith("blob:csv");
    });
});
