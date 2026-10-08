import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { computed, h, ref, shallowRef } from "vue";

import CompareWindow from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/CompareWindow.vue";
import XyWorkshop from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/XyWorkshop.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    ANNOUNCE_KEY,
    LINKED_SELECTION_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
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
import { OPEN_POPUP } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import { reloadXrfSettings } from "@/manuspectrum/pages/AnalysisExplorer/composables/useXrfSettings.ts";
import {
    analysisNode,
    canvasNode,
    elementNode,
    fileNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { loadLineTable } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/xrf/line-table.ts";

import type { DOMWrapper, VueWrapper } from "@vue/test-utils";
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
    legendrank: number;
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
    slots: { value: (NodeId | null)[] };
    nodes: { value: Set<NodeId> };
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
    "#d42515",
    "#008016",
    "#7e58eb",
    "#d251b9",
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

/** The eye's curve id (`XyLegend`'s `LegendEntry.id`) of the curve `curve(slot, n)` builds. */
function curveId(slot: number, n: number): string {
    return `an:${analysisHit(slot + 1).id}:-|${uuid(700 + n)}`;
}

function eyeButton(view: VueWrapper, id: string): DOMWrapper<Element> {
    return view.find(`[data-action="eye"][data-curve="${id}"]`);
}

const FOLIO_CANVAS = "https://iiif.example/f12r";

/** The part of Compare's linked selection the workshop reads, its state set by each spec. */
function fakeLinked(): FakeLinked {
    const selection = ref<NodeId[]>([]);
    const slots = ref<(NodeId | null)[]>([]);
    const nodes = ref(new Set<NodeId>());
    const levels = shallowRef(new Map<NodeId, RelationLevel>());
    const previewLevels = shallowRef(new Map<NodeId, RelationLevel>());
    const toggle = vi.fn();
    const preview = vi.fn();
    const linked = {
        selection: computed(() => selection.value),
        slots: computed(() => slots.value),
        graph: computed(() => ({
            symbols: new Map<string, string>(),
            nodes: nodes.value,
        })),
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
    return {
        linked,
        selection,
        slots,
        nodes,
        levels,
        previewLevels,
        toggle,
        preview,
    };
}

function nextFrame(): Promise<void> {
    return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

let fake: FakeLinked;
let fetchMock: ReturnType<typeof vi.fn>;
let wrapper: VueWrapper | null = null;
let answers: Map<string, Response>;
const announce = vi.fn();

/** Answers each preview by its file number `n`; the others get `SERIES`. */
function answer(n: number, response: Response): void {
    answers.set(`/api/spectrum-preview/${uuid(700 + n)}?n=full`, response);
}

const WINDOW_ID = "auto:xy:test";

async function mountWorkshop(
    curves: FileLine[],
    resize = ref(0),
    windowId = WINDOW_ID,
): Promise<VueWrapper> {
    wrapper = mount(CompareWindow, {
        attachTo: document.body,
        props: { title: "XRF", position: 1, total: 1, size: "M", folded: null },
        slots: { default: () => h(XyWorkshop, { curves, windowId }) },
        global: {
            provide: {
                [WINDOW_RESIZE_KEY as symbol]: resize,
                [LINKED_SELECTION_KEY as symbol]: fake.linked,
                [ANNOUNCE_KEY as symbol]: announce,
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
    setActivePinia(createPinia());
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
    announce.mockClear();
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

    it("draws each curve in the hue of its order in the window, solid, named « A1 · file »", async () => {
        await mountWorkshop([curve(0, 1), curve(0, 2), curve(1, 3)]);
        const { traces, layout } = lastDrawing();
        expect(traces.map((trace) => trace.name)).toEqual([
            "A1 · S1.csv",
            "A1 · S2.csv",
            "A2 · S3.csv",
        ]);
        expect(traces.map((trace) => trace.line.color)).toEqual([
            COLOURS[0],
            COLOURS[1],
            COLOURS[2],
        ]);
        expect(traces.map((trace) => trace.line.dash)).toEqual([
            "solid",
            "solid",
            "solid",
        ]);
        expect(layout.showlegend).toBe(false);
        expect(layout.xaxis.title.text).toBe("Energy (keV)");
        expect(layout.yaxis.title.text).toBe("Counts");
    });

    it("draws lines only, every curve in colour — never grey or a fallback ink — the first file of each slot labelled at its end", async () => {
        await mountWorkshop([
            curve(0, 1),
            curve(0, 2),
            curve(1, 3),
            curve(9, 4),
        ]);
        const { traces, layout } = lastDrawing();
        // Identity trace order now: no curve is drawn under another any more.
        expect(traces.map((trace) => trace.name)).toEqual([
            "A1 · S1.csv",
            "A1 · S2.csv",
            "A2 · S3.csv",
            "A10 · S4.csv",
        ]);
        expect(traces.map((trace) => trace.mode)).toEqual(
            Array(4).fill("lines"),
        );
        expect(traces.every((trace) => trace.marker === undefined)).toBe(true);
        expect(traces.map((trace) => trace.line.color)).toEqual([
            COLOURS[0],
            COLOURS[1],
            COLOURS[2],
            COLOURS[3],
        ]);
        expect(traces.map((trace) => trace.line.width)).toEqual([
            1.5, 1.5, 1.5, 1.5,
        ]);
        expect(traces.map((trace) => trace.opacity)).toEqual([1, 1, 1, 1]);
        expect(traces[0].hovertemplate).toBe(
            "A1 · S1.csv · %{y:.4~g}<extra></extra>",
        );
        expect(traces.map((trace) => trace.legendrank)).toEqual([0, 0, 1, 9]);
        expect(layout.annotations.map((note) => note.text)).toEqual([
            `<span style="color:${COLOURS[0]}">━</span> A1`,
            `<span style="color:${COLOURS[2]}">━</span> A2`,
            `<span style="color:${COLOURS[3]}">━</span> A10`,
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

    it("opens on overlay under nine curves regardless of which slots they are, multiples above", async () => {
        // Every curve takes its own hue now, so no slot special-cases the layout any more.
        await mountWorkshop([curve(8, 1), curve(9, 2)]);
        expect(lastDrawing().layout.grid).toBeUndefined();
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

    it("keeps a curve's colour when an earlier file of the window failed to load", async () => {
        answer(1, jsonResponse({}, 503));
        await mountWorkshop([curve(0, 1), curve(0, 2)]);
        const { traces } = lastDrawing();
        expect(traces.map((trace) => trace.name)).toEqual(["A1 · S2.csv"]);
        expect(traces[0].line.color).toBe(COLOURS[1]);
        expect(traces[0].line.dash).toBe("solid");
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
            "A2 · %{customdata:.4~g}<extra></extra>",
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
        // Identity trace/panel order: no curve is drawn under another any more.
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
        expect(layout.xaxis2).toMatchObject({ matches: "x" });
        expect(layout.xaxis).not.toHaveProperty("matches");
        const texts = layout.annotations.map((note) => note.text);
        curves.forEach((_, index) =>
            expect(texts[index]).toContain(
                `A${index + 1} · MS${index + 1}_f12_XRF_03`,
            ),
        );
        expect(texts.slice(9)).toEqual(["Energy (keV)", "Counts"]);
        // Every panel is its own hue, the 9th (window position 8) included.
        expect(traces[8].line.color).toBe(COLOURS[8]);

        await view.find('[data-layout="overlay"]').trigger("click");
        await flushPromises();
        const overlay = lastDrawing();
        expect(overlay.layout.grid).toBeUndefined();
        // Every curve is its own hue now: all nine get an end label, A9 included.
        expect(overlay.layout.annotations).toHaveLength(9);
        expect(
            overlay.layout.annotations.some((note) => note.text.endsWith("A9")),
        ).toBe(true);
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
        expect(plotly.relayout).not.toHaveBeenCalledWith(
            chart,
            expect.objectContaining({ "xaxis.autorange": true }),
        );
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
            "hovertemplate",
            "line.color",
            "line.dash",
            "line.width",
            "opacity",
        ]);
        // Identity order (no context-first sort any more): the linked curve
        // (index 0) is emphasised, the other two hidden — colour and dash
        // always stay each curve's own; the focus never changes them.
        expect(update.opacity).toEqual([1, 0, 0]);
        expect(update.hoverinfo).toEqual(["all", "skip", "skip"]);
        expect(update["line.width"]).toEqual([2.5, 1.5, 1.5]);
        expect(update["line.color"]).toEqual([
            COLOURS[0],
            COLOURS[1],
            COLOURS[2],
        ]);
        expect(update["line.dash"]).toEqual(["solid", "solid", "solid"]);
        expect(plotly.relayout).toHaveBeenCalledTimes(1);
        expect(plotly.relayout.mock.calls[0][1]).toEqual({
            "annotations[1].opacity": 0,
            "annotations[2].opacity": 0,
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

    it("draws a legend swatch as the chart draws its curve: its window hue, never grey or a fallback ink", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(9, 2)]);
        const strokes = (): string[] =>
            view
                .findAll(".xy-legend .swatch line")
                .map((line) => (line.element as SVGLineElement).style.stroke);
        expect(strokes()).toEqual(["var(--series-1)", "var(--series-2)"]);
        // A link never recolours a curve, only thickens it: the swatch stays the curve's own hue.
        fake.selection.value = [analysisNode(analysisHit(10).id)];
        fake.levels.value = new Map([
            [analysisNode(analysisHit(10).id), "self"],
        ]);
        await flushPromises();
        expect(strokes()).toEqual(["var(--series-1)", "var(--series-2)"]);
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

    it("says so when the legend's eye alone has hidden every curve", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await eyeButton(view, curveId(0, 1)).trigger("click");
        await eyeButton(view, curveId(1, 2)).trigger("click");
        await flushPromises();
        expect(view.find(".isolated").text()).toBe(
            "Every curve is hidden; « Show all spectra » brings them back.",
        );
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
        const [first, second] = view.findAll(
            ".xy-legend .group > .row > .entry",
        );
        expect(first.find(".id").text()).toBe("A1MS1_f12_XRF_03XRF");
        expect(first.find(".technique").text()).toBe("XRF");
        expect(first.find(".ctx .glyph").exists()).toBe(true);
        expect(first.find(".ctx .component").text()).toBe("Border");
        expect(first.find(".ctx .folio").text()).toBe("f. 12r");
        expect(first.find(".ctx .file").text()).toBe("S1.csv");
        expect(second.find(".technique").exists()).toBe(false);
        expect(second.find(".ctx").exists()).toBe(false);
    });

    it("draws a window's only curve solid in the first hue even when its item is slot 21", async () => {
        const view = await mountWorkshop([curve(20, 1)]);
        const { traces, layout } = lastDrawing();
        expect(traces[0].line).toMatchObject({
            color: COLOURS[0],
            dash: "solid",
        });
        expect(
            (view.find(".xy-legend .swatch line").element as SVGLineElement)
                .style.stroke,
        ).toBe("var(--series-1)");
        expect(layout.annotations[0].text).toContain(`color:${COLOURS[0]}">━`);
    });

    it("draws the 13th curve of a window in the first hue, dashed, in its curve, its legend swatch and its end label", async () => {
        const view = await mountWorkshop(
            Array.from({ length: 13 }, (_, index) => curve(index, index + 1)),
        );
        const { traces, layout } = lastDrawing();
        expect(traces[12].line).toMatchObject({
            color: COLOURS[0],
            dash: "6px,2px",
        });
        expect(traces.slice(0, 12).map((trace) => trace.line.dash)).toEqual(
            Array(12).fill("solid"),
        );
        const swatches = view.findAll(".xy-legend .swatch line");
        expect((swatches[12].element as SVGLineElement).style.stroke).toBe(
            "var(--series-1)",
        );
        expect(layout.annotations[12].text).toContain("╍");
    });

    it("colours two windows independently", async () => {
        const first = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        const one = lastDrawing().traces.map((trace) => trace.line.color);
        first.unmount();
        wrapper = null;
        plotly.react.mockClear();
        await mountWorkshop([curve(7, 3)], ref(0), "auto:xy:other");
        const two = lastDrawing().traces.map((trace) => trace.line.color);
        expect(one).toEqual([COLOURS[0], COLOURS[1]]);
        expect(two).toEqual([COLOURS[0]]);
    });

    it("gives the chart, the hover, the legend swatch and the end label the same colour for each curve", async () => {
        const view = await mountWorkshop([
            curve(5, 1),
            curve(2, 2),
            curve(2, 3),
        ]);
        const { traces, layout } = lastDrawing();
        const swatches = view
            .findAll(".xy-legend .swatch line")
            .map((line) => (line.element as SVGLineElement).style.stroke);
        expect(traces.map((trace) => trace.line.color)).toEqual([
            COLOURS[0],
            COLOURS[1],
            COLOURS[2],
        ]);
        // Plotly's hover box takes its swatch from the trace's own line colour.
        // The legend lists the slots in order (A3 with its two files, then A6).
        expect(new Set(swatches)).toEqual(
            new Set(["var(--series-1)", "var(--series-2)", "var(--series-3)"]),
        );
        expect(swatches[0]).toBe("var(--series-2)");
        expect(layout.annotations.map((note) => note.text)).toEqual([
            `<span style="color:${COLOURS[0]}">━</span> A6`,
            `<span style="color:${COLOURS[1]}">━</span> A3`,
        ]);
    });

    it("moves no colour when a file fails to load or another curve joins the window", async () => {
        answer(1, jsonResponse({}, 503));
        const curves = shallowRef([curve(0, 1), curve(1, 2)]);
        wrapper = mount(CompareWindow, {
            attachTo: document.body,
            props: {
                title: "XRF",
                position: 1,
                total: 1,
                size: "M",
                folded: null,
            },
            slots: {
                default: () =>
                    h(XyWorkshop, {
                        curves: curves.value,
                        windowId: WINDOW_ID,
                    }),
            },
            global: {
                provide: {
                    [WINDOW_RESIZE_KEY as symbol]: ref(0),
                    [LINKED_SELECTION_KEY as symbol]: fake.linked,
                },
            },
        });
        await flushPromises();
        expect(
            lastDrawing().traces.map((trace) => [trace.name, trace.line.color]),
        ).toEqual([["A2 · S2.csv", COLOURS[1]]]);
        curves.value = [...curves.value, curve(2, 3)];
        await flushPromises();
        expect(
            lastDrawing().traces.map((trace) => [trace.name, trace.line.color]),
        ).toEqual([
            ["A2 · S2.csv", COLOURS[1]],
            ["A3 · S3.csv", COLOURS[2]],
        ]);
    });

    it("hides a curve with the legend's eye by restyling once, no redraw, independent of the focus", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        plotly.react.mockClear();
        plotly.restyle.mockClear();
        const id = curveId(0, 1);
        expect(eyeButton(view, id).attributes("aria-pressed")).toBe("false");

        await eyeButton(view, id).trigger("click");
        await nextFrame();
        await flushPromises();

        expect(plotly.react).not.toHaveBeenCalled();
        expect(plotly.restyle).toHaveBeenCalledTimes(1);
        const [, update] = plotly.restyle.mock.calls[0] as [
            HTMLElement,
            Record<string, unknown[]>,
        ];
        expect(update.opacity).toEqual([0, 1]);
        expect(update.hoverinfo).toEqual(["skip", "all"]);
        expect(eyeButton(view, id).attributes("aria-pressed")).toBe("true");
        expect(view.findAll(".xy-legend .entry.eye-hidden")).toHaveLength(1);

        await eyeButton(view, id).trigger("click");
        await nextFrame();
        await flushPromises();
        expect(plotly.restyle).toHaveBeenCalledTimes(2);
        expect(
            (plotly.restyle.mock.calls[1][1] as Record<string, unknown[]>)
                .opacity,
        ).toEqual([1, 1]);
        expect(eyeButton(view, id).attributes("aria-pressed")).toBe("false");
    });

    it("gives a hidden curve an empty hovertemplate so Plotly reads its hoverinfo skip", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await eyeButton(view, curveId(0, 1)).trigger("click");
        await nextFrame();
        await flushPromises();
        const update = plotly.restyle.mock.calls.at(-1)?.[1] as {
            hovertemplate: string[];
            hoverinfo: string[];
        };
        expect(update.hoverinfo).toEqual(["skip", "all"]);
        expect(update.hovertemplate[0]).toBe("");
        expect(update.hovertemplate[1]).toContain("A2");
    });

    it("gives a hidden curve back its hovertemplate and hoverinfo all when shown again", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        const id = curveId(0, 1);
        await eyeButton(view, id).trigger("click");
        await nextFrame();
        await flushPromises();
        await eyeButton(view, id).trigger("click");
        await nextFrame();
        await flushPromises();
        const update = plotly.restyle.mock.calls.at(-1)?.[1] as {
            hovertemplate: string[];
            hoverinfo: string[];
        };
        expect(update.hoverinfo).toEqual(["all", "all"]);
        expect(update.hovertemplate[0]).not.toBe("");
        expect(update.hovertemplate[0]).toContain("A1");
    });

    it("recomputes the hovermode from the curves currently shown, a relayout with its hovertemplates, never a redraw", async () => {
        const curves = Array.from({ length: 13 }, (_, index) =>
            curve(index, index + 1),
        );
        const view = await mountWorkshop(curves);
        // 13 shown: past the cap, closest from the start.
        expect(lastDrawing().layout.hovermode).toBe("closest");
        plotly.react.mockClear();
        plotly.restyle.mockClear();
        plotly.relayout.mockClear();

        await eyeButton(view, curveId(0, 1)).trigger("click");
        await eyeButton(view, curveId(1, 2)).trigger("click");
        await nextFrame();
        await flushPromises();

        // 11 shown now (13 minus 2 eye-hidden): back under the cap.
        expect(plotly.react).not.toHaveBeenCalled();
        const hoverCall = plotly.restyle.mock.calls.find(
            (call) => "hovertemplate" in (call[1] as Record<string, unknown>),
        );
        expect(hoverCall).toBeDefined();
        const templates = (hoverCall?.[1] as { hovertemplate: string[] })
            .hovertemplate;
        expect(templates[2]).toBe("A3 · %{y:.4~g}<extra></extra>");
        expect(plotly.relayout).toHaveBeenCalledWith(expect.any(HTMLElement), {
            hovermode: "x unified",
        });
    });

    it("keeps an eye-hidden curve hidden and out of hover however the focus lights it", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await eyeButton(view, curveId(0, 1)).trigger("click");
        await flushPromises();
        plotly.restyle.mockClear();

        fake.selection.value = [analysisNode(analysisHit(1).id)];
        fake.levels.value = new Map([
            [analysisNode(analysisHit(1).id), "self"],
        ]);
        await nextFrame();
        await flushPromises();

        const update = plotly.restyle.mock.calls.at(-1)?.[1] as Record<
            string,
            unknown[]
        >;
        expect(update.opacity[0]).toBe(0);
        expect(update.hoverinfo[0]).toBe("skip");
        expect(
            view
                .findAll(".xy-legend .entry")
                .find(
                    (entry) =>
                        entry.attributes("data-node") ===
                        analysisNode(analysisHit(1).id),
                )
                ?.attributes("aria-pressed"),
        ).toBe("true");
    });

    it("shows a « Show all spectra » action only once a curve is hidden, and shows every one back", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        expect(view.find(".xy-legend .show-all").exists()).toBe(false);
        await eyeButton(view, curveId(0, 1)).trigger("click");
        await flushPromises();
        expect(view.find(".xy-legend .show-all").exists()).toBe(true);

        await view.find(".xy-legend .show-all").trigger("click");
        await flushPromises();
        expect(view.find(".xy-legend .show-all").exists()).toBe(false);
        expect(eyeButton(view, curveId(0, 1)).attributes("aria-pressed")).toBe(
            "false",
        );
    });

    it("keeps the eye's name fixed and states its state through aria-pressed only", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        const nameOf = (): string | null | undefined => {
            const id = eyeButton(view, curveId(0, 1)).attributes(
                "aria-labelledby",
            );
            return id ? document.getElementById(id)?.textContent : undefined;
        };
        const before = nameOf();
        expect(before).toContain("Hide A1");
        await eyeButton(view, curveId(0, 1)).trigger("click");
        await flushPromises();
        expect(nameOf()).toBe(before);
        expect(eyeButton(view, curveId(0, 1)).attributes("aria-pressed")).toBe(
            "true",
        );
    });

    it("moves the focus to the legend's first eye button once « Show all spectra » is pressed", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await eyeButton(view, curveId(1, 2)).trigger("click");
        await flushPromises();
        await view.find(".xy-legend .show-all").trigger("click");
        await flushPromises();
        expect(document.activeElement).toBe(
            eyeButton(view, curveId(0, 1)).element,
        );
    });

    it("forgets a curve's eye-hidden state once it leaves the window", async () => {
        const store = useExplorerStore();
        const view = mount(XyWorkshop, {
            attachTo: document.body,
            props: {
                curves: [curve(0, 1), curve(1, 2)],
                windowId: WINDOW_ID,
            },
            global: {
                provide: { [LINKED_SELECTION_KEY as symbol]: fake.linked },
            },
        });
        wrapper = view;
        await flushPromises();
        await eyeButton(view, curveId(0, 1)).trigger("click");
        expect(store.hiddenCurves[WINDOW_ID]).toEqual([curveId(0, 1)]);

        await view.setProps({ curves: [curve(1, 2)] });
        await flushPromises();
        expect(store.hiddenCurves[WINDOW_ID]).toBeUndefined();
    });

    it("offers Hide or Dim for unrelated curves only while a focus is active, Hide by default", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        expect(view.find(".unrelated-mode").exists()).toBe(false);

        fake.selection.value = [analysisNode(analysisHit(1).id)];
        fake.levels.value = new Map([
            [analysisNode(analysisHit(1).id), "self"],
        ]);
        await flushPromises();
        const mode = view.find(".unrelated-mode");
        expect(mode.exists()).toBe(true);
        expect(mode.find('[data-mode="hide"]').attributes("aria-pressed")).toBe(
            "true",
        );

        plotly.react.mockClear();
        plotly.restyle.mockClear();
        await mode.find('[data-mode="dim"]').trigger("click");
        await nextFrame();
        await flushPromises();
        expect(plotly.react).not.toHaveBeenCalled();
        const update = plotly.restyle.mock.calls.at(-1)?.[1] as Record<
            string,
            unknown[]
        >;
        expect(update.opacity).toEqual([1, 0.35]);
        expect(update["line.color"]).toEqual([COLOURS[0], CONTEXT]);
        expect(update.hoverinfo).toEqual(["all", "skip"]);

        fake.selection.value = [];
        fake.levels.value = new Map();
        await flushPromises();
        expect(view.find(".unrelated-mode").exists()).toBe(false);
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

    it("follows the chart's own box when what sits below it moves it, once per frame", async () => {
        const observers: {
            callback: () => void;
            observed: Element[];
            disconnect: () => void;
        }[] = [];
        vi.stubGlobal(
            "ResizeObserver",
            class {
                observed: Element[] = [];
                disconnect = vi.fn();
                callback: () => void;
                constructor(callback: () => void) {
                    this.callback = callback;
                    observers.push(this);
                }
                observe(element: Element) {
                    this.observed.push(element);
                }
                unobserve() {}
            },
        );
        const view = await mountWorkshop([curve(0, 1)]);
        const element = view.find(".chart").element;
        const watcher = observers.find((o) => o.observed.includes(element));
        expect(watcher).toBeDefined();
        const frame = () =>
            new Promise((resolve) => requestAnimationFrame(resolve));
        watcher!.callback();
        await frame();
        await flushPromises();
        expect(plotly.Plots.resize).not.toHaveBeenCalled();
        Object.defineProperty(element, "clientHeight", { value: 210 });
        watcher!.callback();
        watcher!.callback();
        await frame();
        await flushPromises();
        expect(plotly.Plots.resize).toHaveBeenCalledTimes(1);
        view.unmount();
        wrapper = null;
        expect(watcher!.disconnect).toHaveBeenCalled();
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

describe("XyWorkshop XRF lens", () => {
    const FOCUS_1 = "#123456";

    /** Pins an element and lights every curve of the window through its analysis. */
    function pinElement(symbol: string, lit: number[] = [1, 2]): void {
        const node = elementNode(symbol);
        fake.slots.value = [node];
        fake.selection.value = [node];
        fake.levels.value = new Map<NodeId, RelationLevel>([
            [node, "self"],
            ...lit.map(
                (slot) =>
                    [analysisNode(analysisHit(slot).id), "evidence"] as [
                        NodeId,
                        RelationLevel,
                    ],
            ),
        ]);
    }

    async function settle(): Promise<void> {
        await loadLineTable();
        await flushPromises();
        await nextFrame();
        await flushPromises();
    }

    function shapeCalls(): Record<string, unknown>[] {
        return plotly.relayout.mock.calls
            .map(([, update]) => update)
            .filter((update) => "shapes" in update);
    }

    beforeEach(() => {
        localStorage.clear();
        reloadXrfSettings();
        document.documentElement.style.setProperty("--focus-1", FOCUS_1);
    });

    afterEach(() => {
        localStorage.clear();
        reloadXrfSettings();
    });

    it("draws an element pin as one relayout of the shapes alone, no redraw", async () => {
        await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await settle();
        plotly.react.mockClear();
        plotly.relayout.mockClear();
        pinElement("Pb");
        await nextFrame();
        await flushPromises();
        expect(plotly.react).not.toHaveBeenCalled();
        expect(plotly.relayout).toHaveBeenCalledTimes(1);
        const [, update] = plotly.relayout.mock.calls[0];
        expect(Object.keys(update)).toEqual(["shapes"]);
        const shapes = update.shapes as {
            x0: number;
            line: { color: string };
        }[];
        // Pb Mα1 is the one Pb line inside the 1–3 keV of the fixture's spectra.
        const line = shapes.find((shape) => Math.abs(shape.x0 - 2.346) < 0.01);
        expect(line?.line.color).toBe(FOCUS_1);
    });

    it("shows the same shapes again after another redraw, so a redraw never loses the lines", async () => {
        const view = await mountWorkshop([curve(0, 1)]);
        await settle();
        pinElement("Pb", [1]);
        await nextFrame();
        await flushPromises();
        plotly.react.mockClear();
        await view.find('[data-layout="offset"]').trigger("click");
        await flushPromises();
        const layout = lastDrawing().layout as unknown as {
            shapes: { x0: number }[];
        };
        expect(layout.shapes.some((s) => Math.abs(s.x0 - 2.346) < 0.01)).toBe(
            true,
        );
    });

    it("makes at most one shapes relayout and never a redraw for a pin of an analysis, whose hidden curves drop their instrument ticks", async () => {
        const peakAt = (centre: number) =>
            series(
                Array.from({ length: 2001 }, (_, i) => i / 100),
                Array.from({ length: 2001 }, (_, i) =>
                    Math.round(
                        10 +
                            5000 *
                                Math.exp(
                                    -(((i / 100 - centre) / 0.05) ** 2) / 2,
                                ),
                    ),
                ),
            );
        answer(1, jsonResponse(peakAt(6.4)));
        answer(2, jsonResponse(peakAt(9)));
        await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await settle();
        plotly.relayout.mockClear();
        plotly.react.mockClear();
        fake.selection.value = [analysisNode(analysisHit(1).id)];
        fake.slots.value = [analysisNode(analysisHit(1).id)];
        fake.levels.value = new Map([
            [analysisNode(analysisHit(1).id), "self"],
            [fileNode(uuid(701)), "direct"],
        ]);
        await nextFrame();
        await flushPromises();
        expect(plotly.react).not.toHaveBeenCalled();
        const calls = shapeCalls();
        expect(calls).toHaveLength(1);
        const shapes = calls[0].shapes as { x0: number }[];
        // Curve 2's escape (9 − 1.74) is gone with the curve; curve 1's (4.66) stays.
        expect(shapes.some((s) => Math.abs(s.x0 - 7.26) < 0.02)).toBe(false);
        expect(shapes.some((s) => Math.abs(s.x0 - 4.66) < 0.02)).toBe(true);
    });

    it("draws an element added to the lens without touching the focus", async () => {
        const view = await mountWorkshop([curve(0, 1)]);
        await settle();
        plotly.relayout.mockClear();
        const input = view.find(".xrf-strip input");
        await input.setValue("Pb");
        await input.trigger("keydown", { key: "Enter" });
        await nextFrame();
        await flushPromises();
        expect(shapeCalls()).toHaveLength(1);
        expect(fake.toggle).not.toHaveBeenCalled();
        expect(fake.selection.value).toEqual([]);
        expect(view.find(".xrf-strip li.element").text()).toContain("Pb");
    });

    it("shows no lens controls, strip or shapes for a spectrum that is not XRF", async () => {
        const view = await mountWorkshop([
            curve(0, 1, {
                presetKey: "ftir",
                axisKey: "transmittance|wavenumber (cm-1)|desc",
            }),
        ]);
        await flushPromises();
        pinElement("Pb", [1]);
        await nextFrame();
        await flushPromises();
        expect(view.find(".xrf-lens-controls").exists()).toBe(false);
        expect(view.find(".xrf-strip").exists()).toBe(false);
        expect(
            (lastDrawing().layout as unknown as { shapes?: unknown }).shapes,
        ).toBeUndefined();
        expect(shapeCalls()).toEqual([]);
    });

    it("lays the Y axis on a log scale through a redraw, the hover reading the real values", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await settle();
        plotly.react.mockClear();
        await view.find('[data-scale="log"]').trigger("click");
        await flushPromises();
        expect(plotly.react).toHaveBeenCalledTimes(1);
        const { traces, layout } = lastDrawing();
        expect(layout.yaxis).toMatchObject({ type: "log" });
        expect(traces[0].customdata).toEqual([10, 30, 20]);
        expect(traces[0].hovertemplate).toContain("%{customdata:");
        expect(view.find('[data-scale="log"]').attributes("aria-pressed")).toBe(
            "true",
        );
        plotly.restyle.mockClear();
        pinElement("Pb", [1]);
        await nextFrame();
        await flushPromises();
        const update = plotly.restyle.mock.calls[0][1] as {
            hovertemplate: string[];
        };
        expect(update.hovertemplate[0]).toContain("%{customdata:");
    });

    it("picks the curve nearest the pointer on a log axis, whatever the axis maps", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await settle();
        await view.find('[data-scale="log"]').trigger("click");
        await flushPromises();
        // Plotly: c2p takes data values (linear or log), l2p takes linearised ones.
        const yaxis = {
            c2p: (value: number) => 100 - Math.log10(value) * 30,
            l2p: (value: number) => 100 - value * 30,
            _offset: 0,
        };
        emitPlotly(view.find(".chart").element, "plotly_click", {
            points: [
                { curveNumber: 0, x: 2, y: 1000, yaxis },
                { curveNumber: 1, x: 2, y: 10, yaxis },
            ],
            event: { clientY: 15 },
        });
        expect(fake.toggle).toHaveBeenCalledWith(
            analysisNode(analysisHit(1).id),
        );
    });

    it("keeps the energy range through a Log toggle, a preset or a zoom by hand", async () => {
        const view = await mountWorkshop([curve(0, 1)]);
        await settle();
        await view.find('[data-range="5-15"]').trigger("click");
        await flushPromises();
        plotly.relayout.mockClear();
        plotly.react.mockClear();
        await view.find('[data-scale="log"]').trigger("click");
        await flushPromises();
        expect(plotly.react).toHaveBeenCalledTimes(1);
        expect(plotly.relayout).toHaveBeenCalledWith(expect.any(HTMLElement), {
            "xaxis.range": [5, 15],
            "yaxis.autorange": true,
        });
        expect(
            view.find('[data-range="5-15"]').attributes("aria-pressed"),
        ).toBe("true");
        expect(view.find('[data-action="reset"]').exists()).toBe(true);

        const chart = view.find(".chart").element;
        Object.assign(chart, {
            _fullLayout: {
                xaxis: { range: [1.5, 2.5], autorange: false, _length: 400 },
            },
        });
        emitPlotly(chart, "plotly_relayout", {
            "xaxis.range[0]": 1.5,
            "xaxis.range[1]": 2.5,
        });
        await flushPromises();
        plotly.relayout.mockClear();
        await view.find('[data-scale="linear"]').trigger("click");
        await flushPromises();
        expect(plotly.relayout).toHaveBeenCalledWith(expect.any(HTMLElement), {
            "xaxis.range": [1.5, 2.5],
            "yaxis.range": [0, 31.5],
        });
        expect(
            view.find('[data-range="custom"]').attributes("aria-pressed"),
        ).toBe("true");
    });

    it("goes back to the full range through a Log toggle when none was chosen", async () => {
        const view = await mountWorkshop([curve(0, 1)]);
        await settle();
        plotly.relayout.mockClear();
        await view.find('[data-scale="log"]').trigger("click");
        await flushPromises();
        expect(plotly.relayout).not.toHaveBeenCalled();
        expect(
            view.find('[data-range="full"]').attributes("aria-pressed"),
        ).toBe("true");
    });

    it("does not offer the log scale with Offset, and says why", async () => {
        const view = await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await settle();
        await view.find('[data-scale="log"]').trigger("click");
        await flushPromises();
        plotly.react.mockClear();
        await view.find('[data-layout="offset"]').trigger("click");
        await flushPromises();
        expect(plotly.react).toHaveBeenCalledTimes(1);
        expect(lastDrawing().layout.yaxis).not.toHaveProperty("type");
        plotly.react.mockClear();
        const log = view.find('[data-scale="log"]');
        expect(log.attributes("aria-disabled")).toBe("true");
        expect(log.attributes("aria-pressed")).toBe("false");
        expect(view.find(".xrf-lens-controls").text()).toContain(
            "Not available with Offset",
        );
        await log.trigger("click");
        await flushPromises();
        expect(plotly.react).not.toHaveBeenCalled();
    });

    it("sets an energy range by a relayout of the X axis, which counts as a zoom", async () => {
        const view = await mountWorkshop([curve(0, 1)]);
        await settle();
        plotly.relayout.mockClear();
        plotly.react.mockClear();
        await view.find('[data-range="5-15"]').trigger("click");
        await flushPromises();
        expect(plotly.relayout).toHaveBeenCalledWith(expect.any(HTMLElement), {
            "xaxis.range": [5, 15],
            "yaxis.autorange": true,
        });
        expect(plotly.react).not.toHaveBeenCalled();
        expect(
            view.find('[data-range="5-15"]').attributes("aria-pressed"),
        ).toBe("true");
        expect(view.find('[data-action="reset"]').exists()).toBe(true);
        await view.find('[data-range="full"]').trigger("click");
        await flushPromises();
        expect(plotly.relayout).toHaveBeenLastCalledWith(
            expect.any(HTMLElement),
            { "xaxis.autorange": true, "yaxis.autorange": true },
        );
        expect(view.find('[data-action="reset"]').exists()).toBe(false);
    });

    describe("counts range follows the energy window", () => {
        const WIDE = series(
            [1, 4, 6, 8, 10, 14, 16],
            [900, 80, 50, 200, 120, 60, 999],
        );

        async function mountWide(): Promise<VueWrapper> {
            answer(1, jsonResponse(WIDE));
            const view = await mountWorkshop([curve(0, 1)]);
            await settle();
            plotly.relayout.mockClear();
            plotly.react.mockClear();
            return view;
        }

        it("fits the counts axis to the data inside a preset, with 5 % of headroom, in the same relayout", async () => {
            const view = await mountWide();
            await view.find('[data-range="5-15"]').trigger("click");
            await flushPromises();
            expect(plotly.relayout).toHaveBeenCalledTimes(1);
            expect(plotly.relayout).toHaveBeenCalledWith(
                expect.any(HTMLElement),
                { "xaxis.range": [5, 15], "yaxis.range": [0, 210] },
            );
            expect(plotly.react).not.toHaveBeenCalled();
        });

        it("gives the autorange back on « Toute la plage »", async () => {
            const view = await mountWide();
            await view.find('[data-range="5-15"]').trigger("click");
            await flushPromises();
            await view.find('[data-range="full"]').trigger("click");
            await flushPromises();
            expect(plotly.relayout).toHaveBeenLastCalledWith(
                expect.any(HTMLElement),
                { "xaxis.autorange": true, "yaxis.autorange": true },
            );
        });

        it("fits again in log10 through a Log toggle, keeping the energy range", async () => {
            const view = await mountWide();
            await view.find('[data-range="5-15"]').trigger("click");
            await flushPromises();
            plotly.relayout.mockClear();
            await view.find('[data-scale="log"]').trigger("click");
            await flushPromises();
            const [, update] = plotly.relayout.mock.calls.at(-1) as [
                HTMLElement,
                Record<string, unknown>,
            ];
            expect(update["xaxis.range"]).toEqual([5, 15]);
            const [from, to] = update["yaxis.range"] as number[];
            expect(from).toBeLessThan(Math.log10(50));
            expect(from).toBeGreaterThan(Math.log10(50) - 0.2);
            expect(to).toBeGreaterThan(Math.log10(200));
            expect(to).toBeLessThan(Math.log10(200) + 0.2);
        });

        it("fits the counts axis after a drag of the energy axis alone, but leaves a box zoom's own counts range", async () => {
            const view = await mountWide();
            const chart = view.find(".chart").element;
            Object.assign(chart, {
                _fullLayout: {
                    xaxis: { range: [5, 15], autorange: false, _length: 400 },
                },
            });
            emitPlotly(chart, "plotly_relayout", {
                "xaxis.range[0]": 5,
                "xaxis.range[1]": 15,
            });
            await flushPromises();
            expect(plotly.relayout).toHaveBeenCalledWith(chart, {
                "yaxis.range": [0, 210],
            });
            plotly.relayout.mockClear();
            emitPlotly(chart, "plotly_relayout", {
                "xaxis.range[0]": 5,
                "xaxis.range[1]": 15,
                "yaxis.range[0]": 10,
                "yaxis.range[1]": 100,
            });
            await flushPromises();
            expect(plotly.relayout).not.toHaveBeenCalled();
        });

        it("gives the counts autorange back when the energy axis returns to its autorange", async () => {
            const view = await mountWide();
            const chart = view.find(".chart").element;
            Object.assign(chart, {
                _fullLayout: {
                    xaxis: { range: [0, 20], autorange: true, _length: 400 },
                },
            });
            emitPlotly(chart, "plotly_relayout", { "xaxis.autorange": true });
            await flushPromises();
            expect(plotly.relayout).toHaveBeenCalledWith(chart, {
                "yaxis.autorange": true,
            });
        });
    });

    it("shows « Custom » once the reader zooms by hand, and « Reset the zoom » goes back to the full range", async () => {
        const view = await mountWorkshop([curve(0, 1)]);
        await settle();
        emitPlotly(view.find(".chart").element, "plotly_relayout", {
            "xaxis.range[0]": 1.5,
            "xaxis.range[1]": 2.5,
        });
        await flushPromises();
        const custom = view.find('[data-range="custom"]');
        expect(custom.attributes("aria-pressed")).toBe("true");
        expect(custom.text()).toBe("Custom");
        await view.find('[data-action="reset"]').trigger("click");
        await flushPromises();
        expect(view.find('[data-range="custom"]').exists()).toBe(false);
        expect(
            view.find('[data-range="full"]').attributes("aria-pressed"),
        ).toBe("true");
    });

    it("exports the PNG with the lens shapes shown now and the line table's source", async () => {
        vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(
            () => undefined,
        );
        const view = await mountWorkshop([curve(0, 1)]);
        await settle();
        pinElement("Pb", [1]);
        await nextFrame();
        await flushPromises();
        await view.find('[data-action="png"]').trigger("click");
        await flushPromises();
        const [figure] = plotly.toImage.mock.calls[0] as unknown as [
            {
                layout: LayoutCall & { shapes: { x0: number }[] };
            },
        ];
        expect(
            figure.layout.shapes.some((s) => Math.abs(s.x0 - 2.346) < 0.01),
        ).toBe(true);
        expect(figure.layout.title?.subtitle.text).toMatch(
            /Lines: XrayDB .* \(CC0\), Elam, Ravel &amp; Sieber 2002$/,
        );
    });

    it("names the elements drawn in the chart's label", async () => {
        const view = await mountWorkshop([curve(0, 1)]);
        await settle();
        pinElement("Pb", [1]);
        await flushPromises();
        expect(view.find(".chart").attributes("aria-label")).toContain(
            "XRF lines drawn: Pb; listed below the chart.",
        );
    });

    it("dims the curves an element focus does not light instead of hiding them, and keeps the Hide switch off", async () => {
        const view = await mountWorkshop([
            curve(0, 1),
            curve(1, 2),
            curve(9, 3),
        ]);
        await settle();
        plotly.restyle.mockClear();
        pinElement("Pb", [1]);
        await nextFrame();
        await flushPromises();
        const update = plotly.restyle.mock.calls[0][1] as Record<
            string,
            unknown[]
        >;
        expect(update.opacity).toEqual([1, 0.35, 0.35]);
        expect(update["line.color"]).toEqual([COLOURS[0], CONTEXT, CONTEXT]);
        const hide = view.find('[data-mode="hide"]');
        expect(hide.attributes("aria-disabled")).toBe("true");
        const tip = view.find(`[id="${hide.attributes("aria-describedby")}"]`);
        expect(tip.text()).toBe(
            "Not available while only elements are in the focus: the lens draws them on every spectrum",
        );
        expect(view.find('[data-mode="dim"]').attributes("aria-pressed")).toBe(
            "true",
        );
        await hide.trigger("click");
        expect(plotly.react).toHaveBeenCalledTimes(1);
    });

    it("still hides the curves an analysis focus does not light", async () => {
        await mountWorkshop([curve(0, 1), curve(1, 2)]);
        await settle();
        plotly.restyle.mockClear();
        fake.selection.value = [analysisNode(analysisHit(1).id)];
        fake.levels.value = new Map([
            [analysisNode(analysisHit(1).id), "self"],
        ]);
        await nextFrame();
        await flushPromises();
        const update = plotly.restyle.mock.calls[0][1] as Record<
            string,
            unknown[]
        >;
        expect(update.opacity).toEqual([1, 0]);
    });

    describe("peak identifier", () => {
        /** 2.00 to 2.70 keV in 0.01 steps, flat at 10 counts with one peak of 500 at 2.35. */
        const PEAK = series(
            Array.from({ length: 71 }, (_, i) => 2 + i / 100),
            Array.from({ length: 71 }, (_, i) => (i === 35 ? 500 : 10)),
        );

        async function mountPeak(): Promise<VueWrapper> {
            answer(1, jsonResponse(PEAK));
            const view = await mountWorkshop([curve(0, 1)]);
            await settle();
            return view;
        }

        function toggleButton(view: VueWrapper): DOMWrapper<Element> {
            return view.find('[data-action="identify"]');
        }

        function clickAt(view: VueWrapper, x: number): void {
            emitPlotly(view.find(".chart").element, "plotly_click", {
                points: [{ curveNumber: 0, x, y: 10 }],
                event: {},
            });
        }

        async function identifyAt(view: VueWrapper, x: number): Promise<void> {
            await toggleButton(view).trigger("click");
            clickAt(view, x);
            await flushPromises();
        }

        it("offers « Identify a peak » as a toggle, off at first and only in an XRF window", async () => {
            const view = await mountPeak();
            const button = toggleButton(view);
            expect(button.attributes("aria-pressed")).toBe("false");
            expect(button.attributes("aria-expanded")).toBeUndefined();
            expect(
                view.find(".chart").attributes("data-identifying"),
            ).toBeUndefined();
            await button.trigger("click");
            expect(button.attributes("aria-pressed")).toBe("true");
            expect(
                view.find(".chart").attributes("data-identifying"),
            ).toBeDefined();
        });

        it("leaves the classes Plotly set on the chart alone when the mode toggles", async () => {
            const view = await mountPeak();
            const chart = view.find(".chart").element;
            chart.classList.add("js-plotly-plot");
            await toggleButton(view).trigger("click");
            expect(chart.classList.contains("js-plotly-plot")).toBe(true);
            await toggleButton(view).trigger("click");
            expect(chart.classList.contains("js-plotly-plot")).toBe(true);
        });

        it("opens the candidates at the local maximum of the raw counts on a click, and toggles nothing in the focus", async () => {
            const view = await mountPeak();
            await identifyAt(view, 2.33);
            const dialog = view.find('[role="dialog"]');
            expect(dialog.find("h3").text()).toMatch(
                /^Candidates at 2\.35 keV \(± 0\.\d\d\)$/,
            );
            expect(dialog.find(".checked").text()).toContain("A1");
            expect(dialog.find('li[data-symbol="Pb"]').exists()).toBe(true);
            expect(fake.toggle).not.toHaveBeenCalled();
            const button = toggleButton(view);
            expect(button.attributes("aria-expanded")).toBe("true");
        });

        it("still toggles the focus on a click outside the mode", async () => {
            const view = await mountPeak();
            await identifyAt(view, 2.33);
            await toggleButton(view).trigger("click");
            expect(view.find('[role="dialog"]').exists()).toBe(false);
            emitPlotly(view.find(".chart").element, "plotly_hover", {
                points: [{ curveNumber: 0, x: 2.33, y: 10 }],
                event: { pointerType: "mouse" },
            });
            clickAt(view, 2.33);
            expect(fake.toggle).toHaveBeenCalledTimes(1);
            expect(fake.toggle).toHaveBeenCalledWith(
                analysisNode(analysisHit(1).id),
            );
        });

        it("identifies, rather than toggling, a press that slips into a zoom box under 20 px", async () => {
            const view = await mountPeak();
            await toggleButton(view).trigger("click");
            const chart = view.find(".chart").element;
            Object.assign(chart, {
                _fullLayout: {
                    xaxis: { range: [2, 2.7], autorange: true, _length: 400 },
                    yaxis: { range: [0, 500], autorange: true, _length: 300 },
                },
            });
            emitPlotly(chart, "plotly_hover", {
                points: [{ curveNumber: 0, x: 2.33, y: 10 }],
                event: { pointerType: "mouse" },
            });
            chart.dispatchEvent(new Event("pointerdown"));
            emitPlotly(chart, "plotly_unhover", { points: [], event: {} });
            emitPlotly(chart, "plotly_relayout", {
                "xaxis.range[0]": 2.33,
                "xaxis.range[1]": 2.331,
                "yaxis.range[0]": 10,
                "yaxis.range[1]": 11,
            });
            await flushPromises();
            expect(view.find('[role="dialog"] h3').text()).toContain(
                "2.35 keV",
            );
            expect(fake.toggle).not.toHaveBeenCalled();
        });

        it("moves one channel with ← and →, and to the energy typed in the field", async () => {
            const view = await mountPeak();
            await identifyAt(view, 2.33);
            const input = view.find('[role="dialog"] input');
            expect(input.attributes("step")).toBe("0.01");
            await view.find('[data-action="raise"]').trigger("click");
            expect(view.find(".peak-identifier h3").text()).toContain(
                "2.36 keV",
            );
            expect((input.element as HTMLInputElement).value).toBe("2.36");
            await view.find('[data-action="lower"]').trigger("click");
            await view.find('[data-action="lower"]').trigger("click");
            expect(view.find(".peak-identifier h3").text()).toContain(
                "2.34 keV",
            );
            await input.setValue("2.5");
            expect(view.find(".peak-identifier h3").text()).toContain(
                "2.50 keV",
            );
            expect(fake.toggle).not.toHaveBeenCalled();
        });

        it("toggles el:Pb in the focus with « Pin Pb », offered only for an element of the graph", async () => {
            const view = await mountPeak();
            await identifyAt(view, 2.33);
            expect(
                view.find('li[data-symbol="Pb"] [data-action="pin"]').exists(),
            ).toBe(false);
            fake.nodes.value = new Set([elementNode("Pb")]);
            await flushPromises();
            const pin = view.find('li[data-symbol="Pb"] [data-action="pin"]');
            expect(pin.text()).toBe("Pin Pb");
            await pin.trigger("click");
            expect(fake.toggle).toHaveBeenCalledTimes(1);
            expect(fake.toggle).toHaveBeenCalledWith(elementNode("Pb"));
        });

        it("adds the element to the lens elements with « Show Pb lines », leaving the focus alone", async () => {
            const view = await mountPeak();
            await identifyAt(view, 2.33);
            const lines = view.find(
                'li[data-symbol="Pb"] [data-action="lines"]',
            );
            expect(lines.text()).toBe("Show Pb lines");
            expect(lines.attributes("aria-pressed")).toBe("false");
            await lines.trigger("click");
            await flushPromises();
            expect(
                view
                    .find('li[data-symbol="Pb"] [data-action="lines"]')
                    .attributes("aria-pressed"),
            ).toBe("true");
            expect(view.find(".xrf-strip li.element").text()).toContain("Pb");
            expect(fake.toggle).not.toHaveBeenCalled();
            expect(fake.selection.value).toEqual([]);
        });

        it("closes on Escape, gives the focus back to the toggle and leaves the selection intact", async () => {
            const view = await mountPeak();
            const held = analysisNode(analysisHit(1).id);
            fake.selection.value = [held];
            fake.slots.value = [held];
            await identifyAt(view, 2.33);
            expect(document.activeElement).toBe(
                view.find('[role="dialog"] input').element,
            );
            await view
                .find('[role="dialog"] input')
                .trigger("keydown", { key: "Escape" });
            await flushPromises();
            expect(view.find('[role="dialog"]').exists()).toBe(false);
            expect(document.activeElement).toBe(toggleButton(view).element);
            expect(
                toggleButton(view).attributes("aria-expanded"),
            ).toBeUndefined();
            expect(fake.selection.value).toEqual([held]);
            expect(fake.toggle).not.toHaveBeenCalled();
        });

        it("leaves Escape outside the panel to the page and takes it on the panel and the toggle", async () => {
            const view = await mountPeak();
            await identifyAt(view, 2.33);
            expect(document.querySelector(OPEN_POPUP)).toBeNull();
            const onToggle = new KeyboardEvent("keydown", {
                key: "Escape",
                cancelable: true,
                bubbles: true,
            });
            toggleButton(view).element.dispatchEvent(onToggle);
            await flushPromises();
            expect(onToggle.defaultPrevented).toBe(true);
            expect(view.find('[role="dialog"]').exists()).toBe(false);
        });

        it("announces the number of candidates when the identifier opens", async () => {
            const view = await mountPeak();
            await identifyAt(view, 2.33);
            const count = view.findAll(".peak-identifier .candidate").length;
            expect(count).toBeGreaterThan(0);
            expect(announce).toHaveBeenLastCalledWith(
                expect.stringMatching(/^\d+ candidates? at 2\.35 keV$/),
            );
        });

        it("shows a hint line above the chart while the mode is on and no peak is chosen, and announces it once", async () => {
            const view = await mountPeak();
            expect(view.find(".identify-hint").exists()).toBe(false);
            announce.mockClear();
            await toggleButton(view).trigger("click");
            const hint = view.find(".identify-hint");
            const sentence =
                "Click the top of a peak: the elements with a line at that energy show under the chart.";
            expect(hint.find(":scope > span").text()).toBe(sentence);
            expect(announce).toHaveBeenCalledWith(sentence);
            clickAt(view, 2.33);
            await flushPromises();
            expect(view.find(".identify-hint").exists()).toBe(false);
            expect(announce).toHaveBeenCalledTimes(2);
        });

        it("offers a help button after the hint, named and described by the four rules", async () => {
            const view = await mountPeak();
            await toggleButton(view).trigger("click");
            const help = view.find(
                ".identify-hint [data-action='identify-help']",
            );
            expect(help.exists()).toBe(true);
            const named = document.getElementById(
                help.attributes("aria-labelledby") ?? "",
            );
            expect(named?.textContent).toBe("How to identify a peak");
            const described = document.getElementById(
                help.attributes("aria-describedby") ?? "",
            );
            expect(described?.textContent?.split("\n")).toEqual([
                "The click snaps to the nearest peak top.",
                "Each candidate shows the line that falls there and its confirmation lines, present or absent in the spectrum.",
                "← / → move the energy by one channel; « Show the lines » draws every line of an element.",
                "Hints only: the analyst decides. Escape or the target to leave.",
            ]);
        });

        it("keeps the chart where it is: the identifier follows the chart, before the lens strip", async () => {
            const view = await mountPeak();
            await identifyAt(view, 2.33);
            const html = view.html();
            const at = (marker: string) => html.indexOf(marker);
            expect(at('class="plot-area')).toBeGreaterThan(-1);
            expect(at('class="peak-identifier')).toBeGreaterThan(
                at('class="plot-area'),
            );
            expect(at('class="peak-identifier')).toBeLessThan(
                at('class="xrf-strip'),
            );
        });

        it("marks the identified energy with one dashed line by a shapes relayout alone, moves it with the arrows and removes it on close", async () => {
            const view = await mountPeak();
            await toggleButton(view).trigger("click");
            plotly.react.mockClear();
            plotly.relayout.mockClear();
            clickAt(view, 2.33);
            await nextFrame();
            await flushPromises();
            const marked = () =>
                (
                    shapeCalls().at(-1)?.shapes as {
                        x0: number;
                        line: { dash: string };
                        label?: { text: string };
                    }[]
                ).filter((shape) => shape.label?.text.startsWith("⌖"));
            expect(plotly.react).not.toHaveBeenCalled();
            expect(marked()).toHaveLength(1);
            expect(marked()[0].x0).toBeCloseTo(2.35, 2);
            expect(marked()[0].line.dash).toBe("dash");
            expect(marked()[0].label?.text).toBe("⌖ 2.35 keV");

            await view.find('[data-action="raise"]').trigger("click");
            await nextFrame();
            await flushPromises();
            expect(marked()[0].x0).toBeCloseTo(2.36, 2);
            expect(plotly.react).not.toHaveBeenCalled();

            await toggleButton(view).trigger("click");
            await nextFrame();
            await flushPromises();
            expect(marked()).toHaveLength(0);
        });

        it("closes the identifier and leaves the mode with the toggle", async () => {
            const view = await mountPeak();
            await identifyAt(view, 2.33);
            await toggleButton(view).trigger("click");
            expect(view.find('[role="dialog"]').exists()).toBe(false);
            expect(toggleButton(view).attributes("aria-pressed")).toBe("false");
        });
    });
});
