import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { computed, h, ref, shallowRef } from "vue";

import CompareWindow from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/CompareWindow.vue";
import XyWorkshop from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/XyWorkshop.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    LINKED_SELECTION_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import {
    analysisHit,
    fileEntry,
    label,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    emitPlotly,
    loadPlotly,
    plotly,
    resetPlotly,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/plotly.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";
import {
    analysisNode,
    canvasNode,
    fileNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { VueWrapper } from "@vue/test-utils";
import type {
    FileViewer,
    Series,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type { NodeId } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import type { RelationLevel } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/related.ts";
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
    marker?: unknown;
    opacity: number;
    showlegend?: boolean;
    hovertemplate: string;
    line: { color: string; dash: string; width: number };
    legendgroup: string;
    legendgrouptitle: { text: string };
}

interface LayoutCall {
    showlegend: boolean;
    paper_bgcolor: string;
    grid?: { rows: number; columns: number };
    annotations: { text: string; x: number; y: number; opacity: number }[];
    title?: { text: string; subtitle: { text: string } };
    xaxis: { title: { text: string }; autorange: unknown };
    yaxis: { title: { text: string }; showticklabels?: boolean };
    [axis: string]: unknown;
}

interface FakeLinked {
    linked: LinkedSelection;
    selection: { value: NodeId[] };
    levels: { value: Map<NodeId, RelationLevel> };
    previewLevels: { value: Map<NodeId, RelationLevel> };
    toggle: ReturnType<typeof vi.fn>;
    preview: ReturnType<typeof vi.fn>;
}

const INK = "#1a1a2e";
const CONTEXT = "#8a8999";
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

const FOLIO_CANVAS = "https://iiif.example/f12r";

/** The part of Compare's linked selection the workshop reads, its state set by each spec. */
function fakeLinked(): FakeLinked {
    const selection = ref<NodeId[]>([]);
    const levels = shallowRef(new Map<NodeId, RelationLevel>());
    const previewLevels = shallowRef(new Map<NodeId, RelationLevel>());
    const toggle = vi.fn();
    const preview = vi.fn();
    const linked = {
        selection: computed(() => selection.value),
        levels: computed(() => levels.value),
        relations: computed(
            () =>
                new Map(
                    [...levels.value].map(([id, level]) => [
                        id,
                        { best: level, slots: [{ slot: 1, level }] },
                    ]),
                ),
        ),
        previewing: ref(null),
        previewSlot: computed(() => null),
        nextSlot: computed(() => 1),
        cue: shallowRef({ generation: 0, nodes: new Set() }),
        previewLevels: computed(() => previewLevels.value),
        labelOf: (id: NodeId) =>
            id === canvasNode(FOLIO_CANVAS)
                ? { value: "f. 12r", lang: "" }
                : null,
        toggle,
        preview,
    } as unknown as LinkedSelection;
    return { linked, selection, levels, previewLevels, toggle, preview };
}

function nextFrame(): Promise<void> {
    return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

let fake: FakeLinked;
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
    wrapper = mount(CompareWindow, {
        attachTo: document.body,
        props: { title: "XRF", position: 1, total: 1, size: "M", folded: null },
        slots: { default: () => h(XyWorkshop, { curves }) },
        global: {
            provide: {
                [WINDOW_RESIZE_KEY as symbol]: resize,
                [LINKED_SELECTION_KEY as symbol]: fake.linked,
            },
        },
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
    document.documentElement.style.setProperty("--series-context", CONTEXT);
    fake = fakeLinked();
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
            "6px,2px",
            "solid",
        ]);
        expect(layout.showlegend).toBe(false);
        expect(layout.xaxis.title.text).toBe("Energy (keV)");
        expect(layout.yaxis.title.text).toBe("Counts");
    });

    it("draws lines only, the slots past A8 in grey context under the coloured ones, each coloured slot labelled at the end of its curve", async () => {
        await mountWorkshop([
            curve(0, 1),
            curve(0, 2),
            curve(1, 3),
            curve(9, 4),
        ]);
        const { traces, layout } = lastDrawing();
        expect(traces.map((trace) => trace.name)).toEqual([
            "A10 · S4.csv",
            "A1 · S1.csv",
            "A1 · S2.csv",
            "A2 · S3.csv",
        ]);
        expect(traces.map((trace) => trace.mode)).toEqual(
            Array(4).fill("lines"),
        );
        expect(traces.every((trace) => trace.marker === undefined)).toBe(true);
        expect(traces.map((trace) => trace.line.color)).toEqual([
            CONTEXT,
            COLOURS[0],
            COLOURS[0],
            COLOURS[1],
        ]);
        expect(traces.map((trace) => trace.line.width)).toEqual([
            1.25, 1.5, 1.5, 1.5,
        ]);
        expect(traces.map((trace) => trace.opacity)).toEqual([1, 1, 1, 1]);
        expect(traces[1].hovertemplate).toBe(
            "%{meta[0]}: %{y:.4~g}<extra></extra>",
        );
        expect(traces.map((trace) => trace.legendgrouptitle.text)).toEqual([
            "A10",
            "A1",
            "A1",
            "A2",
        ]);
        expect(layout.annotations.map((note) => note.text)).toEqual([
            `<span style="color:${COLOURS[0]}">━</span> A1`,
            `<span style="color:${COLOURS[1]}">━</span> A2`,
        ]);
        expect(layout.annotations[0]).toMatchObject({ x: 3, y: 20 });
    });

    it("labels a curve on a reversed X axis at its smallest X, its visual end", async () => {
        answer(1, jsonResponse(series([3, 2, 1], [5, 6, 7], true)));
        await mountWorkshop([curve(0, 1)]);
        expect(lastDrawing().layout.annotations[0]).toMatchObject({
            x: 1,
            y: 7,
        });
    });

    it("opens on small multiples when no slot is in colour", async () => {
        await mountWorkshop([curve(8, 1), curve(9, 2)]);
        expect(lastDrawing().layout.grid).toMatchObject({
            rows: 1,
            columns: 2,
        });
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

    it("lifts each offset curve by a step, keeping the real values for the hover, without Y tick labels", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await view.find('[data-layout="offset"]').trigger("click");
        await flushPromises();
        const { traces, layout } = lastDrawing();
        expect(traces[0].y).toEqual([10, 30, 20]);
        expect(traces[1].y).toEqual([32, 52, 42]);
        expect(traces[1].customdata).toEqual([10, 30, 20]);
        expect(traces[1].hovertemplate).toBe(
            "%{meta[0]}: %{customdata:.4~g}<extra></extra>",
        );
        expect(layout.yaxis.title.text).toBe("Counts (offset)");
        expect(layout.yaxis.showticklabels).toBe(false);
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

    it("opens on small multiples above eight curves, one panel per slot zoomed together along X, and goes back to overlay", async () => {
        const curves = Array.from({ length: 9 }, (_, index) =>
            curve(index, index + 1),
        );
        const view = await mountWorkshop(curves);
        const { traces, layout } = lastDrawing();
        expect(layout.grid).toMatchObject({ rows: 3, columns: 3 });
        expect(traces.map((trace) => trace.xaxis)).toEqual([
            "x9",
            "x",
            "x2",
            "x3",
            "x4",
            "x5",
            "x6",
            "x7",
            "x8",
        ]);
        expect(layout.xaxis2).toMatchObject({ matches: "x" });
        expect(layout.xaxis).not.toHaveProperty("matches");
        const texts = layout.annotations.map((note) => note.text);
        curves.forEach((_, index) =>
            expect(texts[index]).toContain(
                `A${index + 1} · MS${index + 1}_f12_XRF_03`,
            ),
        );
        expect(texts.slice(9)).toEqual(["Energy (keV)", "Counts"]);
        expect(traces[0].line.color).toBe(CONTEXT);

        await view.find('[data-layout="overlay"]').trigger("click");
        await flushPromises();
        const overlay = lastDrawing();
        expect(overlay.layout.grid).toBeUndefined();
        expect(overlay.layout.annotations).toHaveLength(8);
        expect(
            overlay.layout.annotations.some((note) => note.text.endsWith("A9")),
        ).toBe(false);
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
        await view.find('[data-action="table"]').trigger("click");
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
        emitPlotly(view.find(".chart").element, "plotly_relayout", {
            "xaxis.range[0]": 3,
            "xaxis.range[1]": 2,
        });
        await flushPromises();
        await view.find('[data-action="reset"]').trigger("click");
        await flushPromises();
        expect(plotly.relayout).toHaveBeenCalledWith(expect.any(HTMLElement), {
            "xaxis.autorange": "reversed",
            "yaxis.autorange": true,
        });
    });

    it("exports the PNG on the page background, with Plotly's legend, a title and a source line, a hidden curve out of the legend", async () => {
        const click = vi
            .spyOn(HTMLAnchorElement.prototype, "click")
            .mockImplementation(() => undefined);
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        fake.selection.value = [analysisNode(analysisHit(1).id)];
        fake.levels.value = new Map([
            [analysisNode(analysisHit(1).id), "self"],
        ]);
        await nextFrame();
        await flushPromises();
        await view.find('[data-action="png"]').trigger("click");
        await flushPromises();
        const [figure, options] = plotly.toImage.mock.calls[0] as [
            { data: TraceCall[]; layout: LayoutCall },
            { format: string },
        ];
        expect(figure.layout.paper_bgcolor).toBe(BACKGROUND);
        expect(figure.layout.plot_bgcolor).toBe(BACKGROUND);
        expect(figure.layout.showlegend).toBe(true);
        expect(figure.layout.title?.text).toBe("Counts against Energy (keV)");
        expect(figure.layout.title?.subtitle.text).toMatch(
            /^Source: ManuSpectrum, http:\/\/localhost/,
        );
        expect(figure.data.map((trace) => trace.showlegend)).toEqual([
            true,
            false,
        ]);
        expect(options.format).toBe("png");
        expect(click).toHaveBeenCalledTimes(1);
    });

    it("says what the CSV holds in its button's tooltip and description", async () => {
        const view = await mountWorkshop([curve(0, 1)]);
        const button = view.find('[data-action="csv"]');
        const note =
            "The CSV holds the values drawn, treatment included and offset left out: two columns per curve.";
        expect(
            document.getElementById(button.attributes("aria-labelledby")!)
                ?.textContent,
        ).toBe("Download CSV");
        expect(
            document.getElementById(button.attributes("aria-describedby")!)
                ?.textContent,
        ).toBe(note);
        expect(
            button.element
                .closest(".help-tip")
                ?.querySelector('[role="tooltip"]')?.textContent,
        ).toContain(note);
    });

    it("puts its actions in its window's header: reset only once zoomed, PNG, CSV and the table as a toggle", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        const actions = (): string[] =>
            view
                .findAll(".head .actions [data-action]")
                .map((button) => button.attributes("data-action")!);
        expect(actions()).toEqual(["png", "csv", "table"]);
        emitPlotly(view.find(".chart").element, "plotly_relayout", {
            "xaxis.range[0]": 1,
            "xaxis.range[1]": 2,
        });
        await flushPromises();
        expect(actions()).toEqual(["reset", "png", "csv", "table"]);
        emitPlotly(view.find(".chart").element, "plotly_relayout", {
            "annotations[0].opacity": 0.3,
        });
        await flushPromises();
        expect(actions()).toEqual(["reset", "png", "csv", "table"]);
        await view.find('[data-action="reset"]').trigger("click");
        await flushPromises();
        expect(actions()).toEqual(["png", "csv", "table"]);

        const table = view.find('[data-action="table"]');
        expect(table.attributes("aria-pressed")).toBe("false");
        await table.trigger("click");
        await flushPromises();
        expect(actions()).toEqual(["csv", "table"]);
        expect(
            view.find('[data-action="table"]').attributes("aria-pressed"),
        ).toBe("true");
    });

    it("takes a press on a curve that slipped into a zoom box under 20 px for a click: the axes go back, the curve toggles", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        const chart = view.find(".chart").element;
        Object.assign(chart, {
            _fullLayout: {
                xaxis: { range: [1, 3], autorange: true, _length: 400 },
                yaxis: { range: [10, 30], autorange: true, _length: 300 },
            },
        });
        const actions = (): string[] =>
            view
                .findAll(".head .actions [data-action]")
                .map((button) => button.attributes("data-action")!);
        emitPlotly(chart, "plotly_hover", {
            points: [{ curveNumber: 1, y: 30 }],
            event: { pointerType: "mouse" },
        });
        chart.dispatchEvent(new Event("pointerdown"));
        emitPlotly(chart, "plotly_unhover", { points: [], event: {} });
        plotly.relayout.mockClear();
        emitPlotly(chart, "plotly_relayout", {
            "xaxis.range[0]": 2,
            "xaxis.range[1]": 2.05,
            "yaxis.range[0]": 20,
            "yaxis.range[1]": 20.5,
        });
        await flushPromises();
        expect(plotly.relayout).toHaveBeenCalledWith(chart, {
            "xaxis.autorange": true,
            "yaxis.autorange": true,
        });
        expect(fake.toggle).toHaveBeenCalledWith(
            analysisNode(analysisHit(2).id),
        );
        expect(actions()).toEqual(["png", "csv", "table"]);

        plotly.relayout.mockClear();
        chart.dispatchEvent(new Event("pointerdown"));
        emitPlotly(chart, "plotly_relayout", {
            "xaxis.range[0]": 1.5,
            "xaxis.range[1]": 2.5,
        });
        await flushPromises();
        expect(plotly.relayout).not.toHaveBeenCalled();
        expect(fake.toggle).toHaveBeenCalledTimes(1);
        expect(actions()).toEqual(["reset", "png", "csv", "table"]);
    });

    it("gives back the chart layout it left for the table", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await view.find('[data-layout="offset"]').trigger("click");
        await view.find('[data-action="table"]').trigger("click");
        await flushPromises();
        expect(
            view
                .findAll(".layouts [aria-pressed='true']")
                .map((button) => button.attributes("data-layout")),
        ).toEqual([]);
        await view.find('[data-action="table"]').trigger("click");
        await flushPromises();
        expect(
            view.find('[data-layout="offset"]').attributes("aria-pressed"),
        ).toBe("true");
    });

    it("offers the chart layouts as icon toggles named by their tooltip", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        const names = view
            .findAll(".layouts [data-layout]")
            .map(
                (button) =>
                    document.getElementById(
                        button.attributes("aria-labelledby")!,
                    )?.textContent,
            );
        expect(names).toEqual(["Overlay", "Offset", "Grid"]);
        expect(view.find('.layouts [data-layout="table"]').exists()).toBe(
            false,
        );
    });

    it("shows a selection by restyling the drawn chart once, style attributes only, hiding the curves it does not link", async () => {
        const view = await mountWorkshop([
            curve(0, 1),
            curve(1, 2),
            curve(9, 3),
        ]);
        plotly.react.mockClear();
        plotly.relayout.mockClear();
        fake.selection.value = [analysisNode(analysisHit(1).id)];
        fake.levels.value = new Map([
            [analysisNode(analysisHit(1).id), "self"],
            [fileNode(uuid(701)), "direct"],
        ]);
        await nextFrame();
        await flushPromises();
        expect(plotly.react).not.toHaveBeenCalled();
        expect(plotly.restyle).toHaveBeenCalledTimes(1);
        const [, update] = plotly.restyle.mock.calls[0] as [
            HTMLElement,
            Record<string, unknown[]>,
        ];
        expect(Object.keys(update).sort()).toEqual([
            "hoverinfo",
            "line.color",
            "line.width",
            "opacity",
        ]);
        expect(update.opacity).toEqual([0, 1, 0]);
        expect(update.hoverinfo).toEqual(["skip", "all", "skip"]);
        expect(update["line.width"]).toEqual([1.25, 2.5, 1.5]);
        expect(plotly.relayout).toHaveBeenCalledTimes(1);
        expect(plotly.relayout.mock.calls[0][1]).toEqual({
            "annotations[1].opacity": 0,
        });
        expect(view.findAll(".xy-legend .entry")).toHaveLength(3);
        expect(
            view
                .findAll(".xy-legend .entry.unrelated")
                .map((entry) => entry.find(".slot").text()),
        ).toEqual(["A2", "A10"]);

        fake.selection.value = [];
        fake.levels.value = new Map();
        await nextFrame();
        await flushPromises();
        expect(plotly.react).not.toHaveBeenCalled();
        expect(plotly.restyle).toHaveBeenCalledTimes(2);
        expect(
            (plotly.restyle.mock.calls[1][1] as Record<string, unknown[]>)
                .opacity,
        ).toEqual([1, 1, 1]);
    });

    it("restyles again to states it failed to show", async () => {
        const error = vi.spyOn(console, "error").mockImplementation(() => {});
        await mountWorkshop([curve(0, 1), curve(1, 2)]);
        plotly.restyle.mockRejectedValueOnce(new Error("restyle failed"));
        const linkedLevels = (): Map<NodeId, RelationLevel> =>
            new Map([[analysisNode(analysisHit(1).id), "self"]]);
        fake.selection.value = [analysisNode(analysisHit(1).id)];
        fake.levels.value = linkedLevels();
        await nextFrame();
        await flushPromises();
        expect(plotly.restyle).toHaveBeenCalledTimes(1);
        expect(error).toHaveBeenCalled();

        fake.levels.value = linkedLevels();
        await nextFrame();
        await flushPromises();
        expect(plotly.restyle).toHaveBeenCalledTimes(2);

        fake.levels.value = linkedLevels();
        await nextFrame();
        await flushPromises();
        expect(plotly.restyle).toHaveBeenCalledTimes(2);
    });

    it("draws a legend swatch as the chart draws its curve: in slot colour, a grey context slot in ink while linked", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(9, 2)]);
        const strokes = (): string[] =>
            view
                .findAll(".xy-legend .swatch line")
                .map((line) => (line.element as SVGLineElement).style.stroke);
        expect(strokes()).toEqual(["var(--series-1)", "var(--series-context)"]);
        fake.selection.value = [analysisNode(analysisHit(10).id)];
        fake.levels.value = new Map([
            [analysisNode(analysisHit(10).id), "self"],
        ]);
        await flushPromises();
        expect(strokes()).toEqual(["var(--series-1)", "var(--ink)"]);
    });

    it("says so when the selection links no curve of the window", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        expect(view.find(".isolated").exists()).toBe(false);
        fake.selection.value = [analysisNode(analysisHit(7).id)];
        await flushPromises();
        expect(view.find(".isolated").text()).toBe(
            "No curve here is linked to the selection; press a legend entry to add it.",
        );
        expect(view.findAll(".xy-legend .entry")).toHaveLength(2);
    });

    it("emphasises what a preview links, hidden by the selection or not", async () => {
        await mountWorkshop([curve(0, 1), curve(1, 2)]);
        fake.selection.value = [analysisNode(analysisHit(1).id)];
        fake.levels.value = new Map([
            [analysisNode(analysisHit(1).id), "self"],
        ]);
        fake.previewLevels.value = new Map([[fileNode(uuid(702)), "self"]]);
        await nextFrame();
        await flushPromises();
        const update = plotly.restyle.mock.calls.at(-1)?.[1] as Record<
            string,
            unknown[]
        >;
        expect(update.opacity).toEqual([1, 1]);
        expect(update["line.width"]).toEqual([2.5, 2.5]);
    });

    it("lists every curve in an HTML legend grouped by slot, a press toggling the analysis, or the file when the slot holds several", async () => {
        const view = await mountWorkshop([
            curve(0, 1),
            curve(0, 2),
            curve(1, 3),
        ]);
        const entries = view.findAll(".xy-legend .entry");
        expect(entries.map((entry) => entry.attributes("data-node"))).toEqual([
            analysisNode(analysisHit(1).id),
            fileNode(uuid(701)),
            fileNode(uuid(702)),
            analysisNode(analysisHit(2).id),
        ]);
        await entries[3].trigger("click");
        await entries[2].trigger("click");
        expect(fake.toggle.mock.calls).toEqual([
            [analysisNode(analysisHit(2).id)],
            [fileNode(uuid(702))],
        ]);
        fake.selection.value = [analysisNode(analysisHit(2).id)];
        fake.levels.value = new Map([
            [analysisNode(analysisHit(2).id), "self"],
        ]);
        await flushPromises();
        const pressed = view.findAll(".xy-legend .entry");
        expect(pressed[3].attributes("aria-pressed")).toBe("true");
        expect(pressed[3].attributes("data-rel")).toBe("self");
        expect(pressed[0].attributes("data-rel")).toBe("none");
        expect(pressed[0].find(".add").exists()).toBe(true);
        expect(
            document.getElementById(pressed[0].attributes("aria-describedby")!)
                ?.textContent,
        ).toBe("Not linked to the selection: press to add it.");
    });

    it("shows a slot's entry pinned only when its own node is, not when one of its files is", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(0, 2)]);
        fake.selection.value = [fileNode(uuid(701))];
        fake.levels.value = new Map([
            [fileNode(uuid(701)), "self"],
            [analysisNode(analysisHit(1).id), "direct"],
        ]);
        await flushPromises();
        expect(
            view
                .findAll(".xy-legend .entry")
                .map((entry) => [
                    entry.attributes("data-rel"),
                    entry.attributes("aria-pressed"),
                ]),
        ).toEqual([
            ["direct", "false"],
            ["self", "true"],
            ["direct", "false"],
        ]);
        expect(view.findAll(".xy-legend .entry.unrelated")).toHaveLength(0);
    });

    it("gives each slot's legend entry two lines: label, analysis and technique, then component, folio and its one file", async () => {
        const placed = curve(0, 1);
        placed.analysis = {
            ...placed.analysis,
            canvas: FOLIO_CANVAS,
            component: {
                id: uuid(951),
                model: "component",
                name: label("Border"),
            },
        };
        const bare = curve(1, 2);
        bare.analysis = { ...bare.analysis, technique: null };
        const view = await mountWorkshop([placed, bare, curve(1, 3)]);
        const [first, second] = view.findAll(".xy-legend .group > .entry");
        expect(first.find(".id").text()).toBe("A1MS1_f12_XRF_03XRF");
        expect(first.find(".technique").text()).toBe("XRF");
        expect(first.find(".ctx .glyph").exists()).toBe(true);
        expect(first.find(".ctx .component").text()).toBe("Border");
        expect(first.find(".ctx .folio").text()).toBe("f. 12r");
        expect(first.find(".ctx .file").text()).toBe("S1.csv");
        expect(second.find(".technique").exists()).toBe(false);
        expect(second.find(".ctx").exists()).toBe(false);
    });

    it("previews the node of a legend entry or a curve under the mouse, and toggles a clicked curve", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        const entry = view.findAll(".xy-legend .entry")[0];
        await entry.trigger("pointerenter", { pointerType: "mouse" });
        await entry.trigger("pointerleave", { pointerType: "mouse" });
        const chart = view.find(".chart").element;
        emitPlotly(chart, "plotly_hover", {
            points: [{ curveNumber: 1, y: 30 }],
            event: { pointerType: "mouse" },
        });
        emitPlotly(chart, "plotly_unhover", { points: [], event: {} });
        emitPlotly(chart, "plotly_click", {
            points: [{ curveNumber: 1, y: 30 }],
            event: {},
        });
        expect(fake.preview.mock.calls).toEqual([
            [
                analysisNode(analysisHit(1).id),
                { pointerType: "mouse", currentTarget: entry.element },
            ],
            [null, { pointerType: "mouse" }],
            [analysisNode(analysisHit(2).id), { pointerType: "mouse" }],
            [null, { pointerType: "mouse" }],
        ]);
        expect(fake.toggle).toHaveBeenCalledWith(
            analysisNode(analysisHit(2).id),
        );
    });

    it("ends the preview it started when it leaves the chart for the table or unmounts, and only then", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await view.find('[data-action="table"]').trigger("click");
        await flushPromises();
        expect(fake.preview).not.toHaveBeenCalled();
        await view.find('[data-action="table"]').trigger("click");
        await flushPromises();

        const chart = view.find(".chart").element;
        emitPlotly(chart, "plotly_hover", {
            points: [{ curveNumber: 1, y: 30 }],
            event: { pointerType: "mouse" },
        });
        await view.find('[data-action="table"]').trigger("click");
        await flushPromises();
        expect(fake.preview).toHaveBeenLastCalledWith(null);
        await view.find('[data-action="table"]').trigger("click");
        await flushPromises();

        fake.preview.mockClear();
        const entry = view.findAll(".xy-legend .entry")[0];
        await entry.trigger("pointerenter", { pointerType: "mouse" });
        view.unmount();
        wrapper = null;
        expect(fake.preview).toHaveBeenLastCalledWith(null);
    });

    it("marks how the selection links each row of the table layout", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        fake.selection.value = [analysisNode(analysisHit(1).id)];
        fake.levels.value = new Map([
            [analysisNode(analysisHit(1).id), "self"],
        ]);
        await view.find('[data-action="table"]').trigger("click");
        expect(
            view
                .findAll(".xy-curve-list tbody tr")
                .map((row) => row.attributes("data-rel")),
        ).toEqual(["self", "none"]);
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
            "# The CSV holds the values drawn, treatment included and offset left out: two columns per curve.",
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
        await view.find('[data-action="table"]').trigger("click");
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
        await view.find('[data-action="table"]').trigger("click");
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

    it("draws small multiples again at their new size once they no longer need a height of their own", async () => {
        const resize = ref(0);
        const view = await mountWorkshop(
            Array.from({ length: 9 }, (_, index) =>
                curve(index % 2, index + 1),
            ),
            resize,
        );
        const element = view.find<HTMLElement>(".chart").element;
        let width = 300;
        Object.defineProperty(element, "clientWidth", { get: () => width });
        Object.defineProperty(element, "clientHeight", {
            get: () =>
                element.style.minBlockSize
                    ? parseFloat(element.style.minBlockSize) * 16
                    : 300,
        });
        resize.value += 1;
        await flushPromises();
        expect(element.style.minBlockSize).not.toBe("");
        const drawings = plotly.react.mock.calls.length;

        width = 1200;
        resize.value += 1;
        await flushPromises();
        expect(element.style.minBlockSize).toBe("");
        expect(plotly.react.mock.calls.length).toBe(drawings + 2);
        expect(plotly.Plots.resize.mock.calls.at(-1)?.[0]).toBe(element);
        resize.value += 1;
        await flushPromises();
        expect(plotly.react.mock.calls.length).toBe(drawings + 2);
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
