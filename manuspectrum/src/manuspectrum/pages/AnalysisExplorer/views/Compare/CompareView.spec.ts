import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import CompareView from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/CompareView.vue";
import WindowGrid from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/WindowGrid.vue";
import XyWorkshop from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/XyWorkshop.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisHit,
    characterization,
    documentPayload,
    fileEntry,
    imagingEntry,
    technique,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    installDialog,
    pressEscape,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/dialog.ts";
import {
    stubIiifLayer,
    stubSideBySide,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";
import { resetFakeGrids } from "@/manuspectrum/pages/AnalysisExplorer/testing/gridstack.ts";
import {
    plotly,
    resetPlotly,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/plotly.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";
import { LAYOUT_STORAGE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/layout.ts";

import type { Pinia } from "pinia";
import type { VueWrapper } from "@vue/test-utils";
import type {
    FileEntry,
    Item,
    SynthesisResponse,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

vi.hoisted(() => {
    // jsdom's SVG has no createSVGRect: without it Leaflet has no path renderer.
    (
        SVGSVGElement.prototype as unknown as { createSVGRect: () => object }
    ).createSVGRect = () => ({});
});
vi.mock("leaflet-iiif", () => ({}));
vi.mock("leaflet-side-by-side", () => ({}));

vi.mock("gridstack", async () =>
    (
        await import(
            "@/manuspectrum/pages/AnalysisExplorer/testing/gridstack.ts"
        )
    ).gridstackModule(),
);

vi.mock("@/manuspectrum/pages/AnalysisExplorer/xy/plotly.ts", async () =>
    (
        await import("@/manuspectrum/pages/AnalysisExplorer/testing/plotly.ts")
    ).plotlyModule(),
);

vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (name: string) =>
        name.endsWith("synthesis")
            ? "/en/api/explorer/synthesis"
            : "/en/api/explorer/items",
}));

const XRF = "counts|energy (kev)|asc";
const RAMAN = "intensity|raman shift|asc";
const FORS = "reflectance|wavelength|asc";
const FTIR = "reflectance|wavenumber|desc";

const SERIES_PATH = "/api/spectrum-preview/";
const SYNTHESIS_PATH = "/en/api/explorer/synthesis";

const SYNTHESIS: SynthesisResponse = {
    coverage: [
        {
            canvas: "https://iiif.example/c1",
            label: "f. 12r",
            document: uuid(1),
            counts: { xrf: 1 },
            components: [{ component: null, counts: { xrf: 1 } }],
        },
    ],
    canvases: [
        {
            canvas: "https://iiif.example/c1",
            label: "f. 12r",
            document: uuid(1),
            selected: true,
            analyses: [],
            materials: [],
        },
    ],
    techniques: [technique("http://example.org/xrf", "XRF", 1, "xrf")],
    pairs: [],
    elements: [{ symbol: "Cu", level: null, count: 1, materials: [] }],
    materials: [],
    unpublishedCount: 0,
};

function spectrum(n: number, axisKey: string, extra = {}): FileEntry {
    const base = fileEntry();
    return fileEntry({
        id: uuid(700 + n),
        name: `S${n}.csv`,
        previewUrl: `http://testserver${SERIES_PATH}${uuid(700 + n)}`,
        viewer: { ...base.viewer, axisKey, ...extra },
    });
}

function whole(n: number, files: FileEntry[]): Item {
    const analysis = analysisHit(n);
    return { key: `an:${analysis.id}:-`, kind: "analysis", analysis, files };
}

const XRF_ITEM = whole(1, [
    spectrum(1, XRF, { configName: "XRF — energy / counts" }),
]);
const RAMAN_ITEM = whole(2, [
    spectrum(2, RAMAN, {
        configName: null,
        xLabel: "Raman shift (cm-1)",
        yLabel: "Intensity",
    }),
]);
const MICRO_ITEM = whole(3, [
    fileEntry({
        id: uuid(760),
        name: "M1.jpg",
        dataKind: "micro-imaging",
        role: "other",
        downloadUrl: "/files/m1.jpg",
        previewUrl: null,
    }),
]);
const MATERIAL: Item = {
    key: `ch:${uuid(501)}:-`,
    kind: "characterization",
    characterization: characterization(1),
};
const EMPTY_ITEM = whole(4, []);
const FORS_ITEM = whole(5, [spectrum(5, FORS)]);
const FTIR_ITEM = whole(6, [spectrum(6, FTIR)]);
const XRF_OTHER_ITEM = whole(7, [spectrum(7, XRF)]);
const XRF_THIRD_ITEM = whole(9, [spectrum(9, XRF)]);
const XRF_EIGHT_ITEM = whole(
    10,
    Array.from({ length: 8 }, (_, index) => spectrum(10 + index, XRF)),
);
const MAPS_ITEM = whole(8, [imagingEntry()]);
const COMPONENT_ITEM: Item = {
    key: `an:${analysisHit(11).id}:-`,
    kind: "analysis",
    analysis: {
        ...analysisHit(11),
        component: {
            id: uuid(951),
            model: "component",
            name: { value: "Initial T", lang: "en" },
        },
    },
    files: [spectrum(11, XRF)],
};

const ITEMS = new Map(
    [
        XRF_ITEM,
        RAMAN_ITEM,
        MICRO_ITEM,
        MATERIAL,
        EMPTY_ITEM,
        FORS_ITEM,
        FTIR_ITEM,
        XRF_OTHER_ITEM,
        MAPS_ITEM,
        XRF_THIRD_ITEM,
        XRF_EIGHT_ITEM,
        COMPONENT_ITEM,
    ].map((item) => [item.key, item]),
);

let pinia: Pinia;
let announce: ReturnType<typeof vi.fn>;
let fetchMock: ReturnType<typeof vi.fn>;
let synthesis: SynthesisResponse;
/** Answers the next synthesis requests instead of `synthesis`, while set. */
let synthesisReply: (() => Promise<Response>) | null = null;
let wrapper: VueWrapper | null = null;
let uninstallDialog: () => void;

beforeEach(() => {
    stubIiifLayer({ size: { w: 2000, h: 3000 } });
    stubSideBySide();
    uninstallDialog = installDialog();
    resetFakeGrids();
    forgetPayloads();
    window.localStorage.clear();
    announce = vi.fn();
    resetPlotly();
    synthesis = SYNTHESIS;
    synthesisReply = null;
    fetchMock = vi.fn(async (url: string) => {
        if (url.startsWith(SYNTHESIS_PATH)) {
            return synthesisReply ? synthesisReply() : jsonResponse(synthesis);
        }
        if (url.startsWith(SERIES_PATH)) {
            return jsonResponse({
                x: [1, 2],
                y: [3, 4],
                n_source: 2,
                decimated: false,
                x_reversed: false,
            });
        }
        const keys = new URLSearchParams(url.split("?")[1]).getAll("ids");
        return jsonResponse({
            items: keys.flatMap((key) => ITEMS.get(key) ?? []),
            missing: keys.filter((key) => !ITEMS.has(key)),
        });
    });
    vi.stubGlobal("fetch", fetchMock);
    pinia = createPinia();
    setActivePinia(pinia);
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    uninstallDialog();
    vi.unstubAllGlobals();
});

function select(...items: Item[]): void {
    useExplorerStore().addManyToBasket(items.map((item) => item.key));
}

/** The requests of the items API. */
function itemCalls(): string[] {
    return fetchMock.mock.calls
        .map(([url]) => String(url))
        .filter((url) => url.startsWith("/en/api/explorer/items"));
}

function synthesisCalls(): string[] {
    return fetchMock.mock.calls
        .map(([url]) => String(url))
        .filter((url) => url.startsWith(SYNTHESIS_PATH));
}

async function openTool(view: VueWrapper, kind: string): Promise<void> {
    await view.find("button.tool-menu-button").trigger("click");
    await view.find(`[role="menuitem"][data-tool="${kind}"]`).trigger("click");
    await flushPromises();
}

function seriesCalls(): string[] {
    return fetchMock.mock.calls
        .map(([url]) => String(url))
        .filter((url) => url.startsWith(SERIES_PATH));
}

async function mountView(): Promise<VueWrapper> {
    wrapper = mount(CompareView, {
        attachTo: document.body,
        global: {
            plugins: [pinia],
            provide: { [ANNOUNCE_KEY as symbol]: announce },
        },
    });
    await flushPromises();
    return wrapper;
}

function windowIds(view: VueWrapper): (string | undefined)[] {
    return view
        .findAll(".grid-stack-item")
        .map((item) => item.attributes("data-window-id"));
}

function windowOf(view: VueWrapper, id: string) {
    return view
        .findAll(".grid-stack-item")
        .find((item) => item.attributes("data-window-id") === id)!;
}

function hiddenButton(view: VueWrapper) {
    return view.find(".hidden-windows .hidden-windows-button");
}

/** The entries of « Hidden windows », its menu opened first. */
async function hiddenEntries(view: VueWrapper) {
    if (hiddenButton(view).attributes("aria-expanded") !== "true") {
        await hiddenButton(view).trigger("click");
    }
    return view.findAll('.hidden-windows [role="menuitem"]');
}

/** The synthesis with the identified material of `MATERIAL`, citing the analysis of `XRF_ITEM`. */
function citingSynthesis(selected: boolean): SynthesisResponse {
    return {
        ...SYNTHESIS,
        materials: [
            {
                id: characterization(1).id,
                evidence: [analysisHit(1).id],
                canvases: [],
                objects: [],
                summary: characterization(1),
                selected,
            },
        ],
    };
}

/** The Selection column of each line of the Materials window. */
function materialSelection(view: VueWrapper): string[] {
    return windowOf(view, "auto:characterizations")
        .findAll("tbody td .selection")
        .map((cell) => cell.text());
}

function storedLayout(): {
    boxes: Record<string, object>;
    hidden: string[];
    tools?: object[];
} | null {
    const raw = window.localStorage.getItem(LAYOUT_STORAGE_KEY);
    return raw === null ? null : JSON.parse(raw);
}

describe("CompareView", () => {
    it("says how to fill an empty Selection, with no windows", async () => {
        const view = await mountView();
        expect(view.find(".empty").text()).toBe(
            "Your Selection is empty. Add analyses or identified materials with « + Selection ».",
        );
        expect(view.find(".grid-stack").exists()).toBe(false);
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it("waits for the Selection to be read before it arranges the windows", async () => {
        select(XRF_ITEM);
        let answer: (response: Response) => void = () => undefined;
        fetchMock.mockImplementationOnce(
            () => new Promise<Response>((resolve) => (answer = resolve)),
        );
        const view = await mountView();
        expect(view.find(".grid-stack").exists()).toBe(false);
        expect(view.find(".loading").text()).toBe("Reading the Selection…");
        answer(jsonResponse({ items: [XRF_ITEM], missing: [] }));
        await flushPromises();
        expect(windowIds(view)).toEqual([`auto:xy:${XRF}`]);
    });

    it("offers to read the Selection again when the service fails", async () => {
        select(XRF_ITEM);
        fetchMock.mockImplementationOnce(async () =>
            jsonResponse({ error: "down" }, 500),
        );
        const view = await mountView();
        expect(view.find(".unavailable-state").exists()).toBe(true);
        await view.find(".unavailable-state .retry").trigger("click");
        await flushPromises();
        expect(windowIds(view)).toEqual([`auto:xy:${XRF}`]);
    });

    it("arranges the windows from the Selection, titled by the stored configuration", async () => {
        select(MATERIAL, RAMAN_ITEM, XRF_ITEM, MICRO_ITEM, EMPTY_ITEM);
        const view = await mountView();
        expect(windowIds(view)).toEqual([
            `auto:xy:${RAMAN}`,
            `auto:xy:${XRF}`,
            "auto:micro",
            "auto:characterizations",
            "auto:not-in-chart",
        ]);
        expect(
            view
                .findAll(".compare-window h3 .name")
                .map((title) => title.text()),
        ).toEqual([
            "Intensity against Raman shift (cm-1)",
            "XRF — energy / counts",
            "Micro-images",
            "Materials",
            "Without visualisation",
        ]);
        expect(
            view
                .findAll(".compare-window h3")
                .map((title) => title.find(".kind").exists()),
        ).toEqual([true, true, false, false, false]);
        expect(
            view
                .findAll(".compare-window h3 .subtitle")
                .map((title) => title.text()),
        ).toEqual([
            "1 spectrum",
            "1 spectrum",
            "1 image",
            "1 identified material",
            "1 item",
        ]);
        expect(
            view.findAllComponents(XyWorkshop).map((xy) => xy.props("title")),
        ).toEqual([
            "Intensity against Raman shift (cm-1)",
            "XRF — energy / counts",
        ]);
        expect(
            plotly.react.mock.calls.flatMap(([, traces]) =>
                (traces as { name: string }[]).map((trace) => trace.name),
            ),
        ).toContain("A3 · S1.csv");
        expect(
            windowOf(view, "auto:micro").find("figcaption").text(),
        ).toContain("A4");
        expect(
            windowOf(view, "auto:characterizations")
                .find("tbody th button")
                .attributes("title"),
        ).toBe("Characterization 1");
        expect(windowOf(view, "auto:not-in-chart").find(".reason").text()).toBe(
            "No data to display.",
        );
    });

    it("lists the components of the Selection under the toolbar, none when it has none", async () => {
        select(XRF_ITEM);
        const view = await mountView();
        expect(view.find(".component-strip").exists()).toBe(false);
        select(COMPONENT_ITEM);
        await flushPromises();
        const strip = view.find(".window-grid > .component-strip");
        expect(strip.exists()).toBe(true);
        expect(strip.findAll(".chip").map((chip) => chip.text())).toEqual([
            "Initial T1 · 0",
        ]);
        expect(
            strip.element.previousElementSibling?.classList.contains("toolbar"),
        ).toBe(true);
    });

    it("opens every window and every tool at size M", async () => {
        select(
            MATERIAL,
            RAMAN_ITEM,
            XRF_ITEM,
            MICRO_ITEM,
            EMPTY_ITEM,
            MAPS_ITEM,
        );
        const view = await mountView();
        for (const kind of ["coverage", "periodic"]) {
            await openTool(view, kind);
        }
        const sizes = view
            .findComponent(WindowGrid)
            .props("windows")
            .map((spec: { id: string; size: string }) => [spec.id, spec.size]);
        expect(sizes.length).toBe(8);
        expect(sizes.filter(([, size]) => size !== "M")).toEqual([]);
    });

    it("puts the layered maps on the light table in their own window, not among the items in no chart", async () => {
        select(MAPS_ITEM, EMPTY_ITEM);
        const view = await mountView();
        expect(windowIds(view)).toEqual([
            "auto:chemical-imaging",
            "auto:not-in-chart",
        ]);
        const maps = windowOf(view, "auto:chemical-imaging");
        expect(maps.find("h3 .name").text()).toBe("Imaging");
        expect(maps.find("h3 .subtitle").text()).toBe(
            "1 analysis · 2 canvases",
        );
        expect(maps.find(".light-table").exists()).toBe(true);
        expect(maps.find(".curtain-pane").exists()).toBe(true);
        expect(
            maps
                .findAll(".curtain-pane .chip .label")
                .map((node) => node.text()),
        ).toEqual(["Pb", "Hg"]);
        expect(windowOf(view, "auto:not-in-chart").findAll("li")).toHaveLength(
            1,
        );
    });

    it("counts the analyses and the canvases of the light table", async () => {
        select(MAPS_ITEM, whole(12, [imagingEntry()]));
        ITEMS.set(whole(12, [imagingEntry()]).key, whole(12, [imagingEntry()]));
        const view = await mountView();
        expect(
            windowOf(view, "auto:chemical-imaging").find("h3 .subtitle").text(),
        ).toBe("2 analyses · 4 canvases");
        ITEMS.delete(whole(12, [imagingEntry()]).key);
    });

    it("keeps the window id, so a box saved for it is applied again", async () => {
        select(MAPS_ITEM);
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({
                version: 2,
                boxes: { "auto:chemical-imaging": { x: 6, y: 0, w: 6, h: 5 } },
                hidden: [],
                folded: { "auto:chemical-imaging": false },
            }),
        );
        const view = await mountView();
        expect(windowIds(view)).toEqual(["auto:chemical-imaging"]);
        expect(
            windowOf(view, "auto:chemical-imaging")
                .find('[data-action="fold"]')
                .attributes("aria-expanded"),
        ).toBe("true");
        expect(storedLayout()?.boxes["auto:chemical-imaging"]).toMatchObject({
            x: 6,
            w: 6,
        });
    });

    it("opens the fourth XY window folded to its header", async () => {
        select(XRF_ITEM, RAMAN_ITEM, FORS_ITEM, FTIR_ITEM);
        const view = await mountView();
        const folded = windowOf(view, `auto:xy:${FTIR}`);
        expect(
            folded.find('[data-action="fold"]').attributes("aria-expanded"),
        ).toBe("false");
        expect(folded.find(".xy-workshop").exists()).toBe(false);
        expect(
            windowOf(view, `auto:xy:${FORS}`)
                .find('[data-action="fold"]')
                .attributes("aria-expanded"),
        ).toBe("true");
    });

    it("sums a folded XY window up under its header and draws it from there", async () => {
        select(XRF_ITEM, RAMAN_ITEM, FORS_ITEM, FTIR_ITEM);
        const view = await mountView();
        const folded = windowOf(view, `auto:xy:${FTIR}`);
        expect(folded.find(".folded-summary .line").text()).toBe(
            "1 XRF spectrum, not drawn",
        );
        expect(
            folded.findAll(".folded-summary .slots li").map((li) => li.text()),
        ).toEqual(["A4"]);
        expect(
            windowOf(view, `auto:xy:${FORS}`).find(".folded-summary").exists(),
        ).toBe(false);
        await folded.find(".folded-summary button.unfold").trigger("click");
        await flushPromises();
        expect(seriesCalls()).toContain(`${SERIES_PATH}${uuid(706)}?n=full`);
        expect(folded.find(".folded-summary").exists()).toBe(false);
    });

    it("reads the spectra of a folded XY window only once it is unfolded", async () => {
        select(XRF_ITEM, RAMAN_ITEM, FORS_ITEM, FTIR_ITEM);
        const view = await mountView();
        const ftir = `${SERIES_PATH}${uuid(706)}?n=full`;
        expect(seriesCalls()).toHaveLength(3);
        expect(seriesCalls()).not.toContain(ftir);
        await windowOf(view, `auto:xy:${FTIR}`)
            .find('[data-action="fold"]')
            .trigger("click");
        await flushPromises();
        expect(seriesCalls()).toContain(ftir);
    });

    it("hides a closed window without changing the Selection, and lists it to show it again", async () => {
        select(XRF_ITEM, MATERIAL);
        const store = useExplorerStore();
        const view = await mountView();
        await windowOf(view, "auto:characterizations")
            .find('[data-action="close"]')
            .trigger("click");
        await flushPromises();
        expect(store.basket.map((item) => item.key)).toEqual([
            XRF_ITEM.key,
            MATERIAL.key,
        ]);
        expect(windowIds(view)).toEqual([`auto:xy:${XRF}`]);
        expect(announce).toHaveBeenLastCalledWith(
            "Materials hidden. Show it again from « Hidden windows ».",
        );
        expect(storedLayout()?.hidden).toEqual(["auto:characterizations"]);
        expect(hiddenButton(view).text()).toBe("Hidden windows (1)");
        expect(hiddenButton(view).attributes("aria-disabled")).toBeUndefined();
        const [show] = await hiddenEntries(view);
        expect(show.text()).toBe("Show Materials");
        await show.trigger("click");
        await flushPromises();
        expect(windowIds(view)).toEqual([
            `auto:xy:${XRF}`,
            "auto:characterizations",
        ]);
        expect(hiddenButton(view).text()).toBe("Hidden windows (0)");
        expect(hiddenButton(view).attributes("aria-disabled")).toBe("true");
        expect(storedLayout()?.hidden).toEqual([]);
        expect(document.activeElement).toBe(
            windowOf(view, "auto:characterizations").find(".compare-window")
                .element,
        );
    });

    it("keeps a window hidden when the view opens again", async () => {
        select(XRF_ITEM, MATERIAL);
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({
                version: 2,
                boxes: {},
                hidden: [`auto:xy:${XRF}`],
            }),
        );
        const view = await mountView();
        expect(windowIds(view)).toEqual(["auto:characterizations"]);
        expect((await hiddenEntries(view))[0].text()).toBe(
            "Show XRF — energy / counts",
        );
        select(XRF_OTHER_ITEM);
        await flushPromises();
        expect(view.find(".hidden-windows .badge").text()).toBe(
            "1 spectrum added",
        );
    });

    it("reads a layout saved before windows could be hidden", async () => {
        select(XRF_ITEM);
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({
                [`auto:xy:${XRF}`]: { x: 6, y: 0, w: 6, h: 5 },
            }),
        );
        const view = await mountView();
        expect(windowIds(view)).toEqual([`auto:xy:${XRF}`]);
        expect(hiddenButton(view).attributes("aria-disabled")).toBe("true");
    });

    it("keeps the hidden windows hidden when the windows are rearranged", async () => {
        select(XRF_ITEM, MATERIAL);
        const view = await mountView();
        await windowOf(view, `auto:xy:${XRF}`)
            .find('[data-action="close"]')
            .trigger("click");
        await flushPromises();
        await view.find("button.rearrange").trigger("click");
        await flushPromises();
        expect(windowIds(view)).toEqual(["auto:characterizations"]);
        expect(hiddenButton(view).text()).toBe("Hidden windows (1)");
        expect(storedLayout()?.hidden).toEqual([`auto:xy:${XRF}`]);
        expect(announce).toHaveBeenLastCalledWith(
            "Windows rearranged. 1 window stays hidden.",
        );
    });

    it("offers « Hidden windows » in the toolbar, disabled while no window is hidden", async () => {
        select(XRF_ITEM);
        const view = await mountView();
        const button = hiddenButton(view);
        expect(button.text()).toBe("Hidden windows (0)");
        expect(button.attributes("aria-disabled")).toBe("true");
        expect(button.attributes("aria-haspopup")).toBe("menu");
        await button.trigger("click");
        expect(view.find('.hidden-windows [role="menu"]').exists()).toBe(false);
        expect(
            view.find(".window-grid .toolbar .hidden-windows").exists(),
        ).toBe(true);
    });

    it("keeps the rearrange button when every window is hidden", async () => {
        select(XRF_ITEM);
        const view = await mountView();
        await windowOf(view, `auto:xy:${XRF}`)
            .find('[data-action="close"]')
            .trigger("click");
        await flushPromises();
        expect(windowIds(view)).toEqual([]);
        expect(view.find("button.rearrange").exists()).toBe(true);
        expect(document.activeElement).toBe(hiddenButton(view).element);
    });

    it("drops a window whose items leave the Selection, and forgets it", async () => {
        select(XRF_ITEM, MATERIAL);
        window.localStorage.setItem(
            LAYOUT_STORAGE_KEY,
            JSON.stringify({
                version: 2,
                boxes: { [`auto:xy:${XRF}`]: { x: 0, y: 0, w: 6, h: 5 } },
                hidden: ["auto:characterizations"],
            }),
        );
        const view = await mountView();
        const store = useExplorerStore();
        store.removeFromBasket(MATERIAL.key);
        store.removeFromBasket(XRF_ITEM.key);
        await flushPromises();
        expect(view.find(".grid-stack").exists()).toBe(false);
        expect(view.find(".hidden-windows").exists()).toBe(false);
        expect(storedLayout()).toEqual({
            version: 3,
            boxes: {},
            hidden: [],
            folded: {},
        });
    });

    it("stops counting an identified material removed from the Selection as its own, and keeps its window while the next synthesis is read", async () => {
        synthesis = citingSynthesis(true);
        select(XRF_ITEM, MATERIAL);
        const view = await mountView();
        expect(materialSelection(view)).toEqual(["A2"]);
        let answer: (response: Response) => void = () => undefined;
        synthesisReply = () =>
            new Promise<Response>((resolve) => (answer = resolve));
        useExplorerStore().removeFromBasket(MATERIAL.key);
        await flushPromises();
        expect(windowIds(view)).toContain("auto:characterizations");
        expect(materialSelection(view)).toEqual(["cites A1"]);
        answer(jsonResponse(citingSynthesis(false)));
        await flushPromises();
        expect(materialSelection(view)).toEqual(["cites A1"]);
    });

    it("lists no identified material of a previous synthesis once the next one fails", async () => {
        synthesis = citingSynthesis(false);
        select(XRF_ITEM);
        const view = await mountView();
        expect(windowIds(view)).toContain("auto:characterizations");
        synthesisReply = async () => jsonResponse({ error: "down" }, 500);
        select(RAMAN_ITEM);
        await flushPromises();
        expect(windowIds(view)).not.toContain("auto:characterizations");
    });

    it("adds the windows of an item added later, reading only that item", async () => {
        select(XRF_ITEM);
        const view = await mountView();
        select(MATERIAL);
        await flushPromises();
        expect(windowIds(view)).toEqual([
            `auto:xy:${XRF}`,
            "auto:characterizations",
        ]);
        expect(itemCalls()).toHaveLength(2);
        expect(itemCalls()[1]).toContain(encodeURIComponent(MATERIAL.key));
        expect(itemCalls()[1]).not.toContain(encodeURIComponent(XRF_ITEM.key));
    });

    it("arranges the windows at once from items the Selection panel already read", async () => {
        select(XRF_ITEM);
        const first = await mountView();
        first.unmount();
        wrapper = null;
        const view = await mountView();
        expect(windowIds(view)).toEqual([`auto:xy:${XRF}`]);
        expect(itemCalls()).toHaveLength(1);
    });

    it("shows a failure to read an item added later, with a retry, and keeps the windows", async () => {
        select(XRF_ITEM);
        const view = await mountView();
        fetchMock.mockImplementationOnce(async () =>
            jsonResponse({ error: "down" }, 500),
        );
        select(MATERIAL);
        await flushPromises();
        expect(windowIds(view)).toEqual([`auto:xy:${XRF}`]);
        expect(view.find(".unavailable-state").exists()).toBe(true);
        await view.find(".unavailable-state .retry").trigger("click");
        await flushPromises();
        expect(view.find(".unavailable-state").exists()).toBe(false);
        expect(windowIds(view)).toEqual([
            `auto:xy:${XRF}`,
            "auto:characterizations",
        ]);
    });

    it("counts the new spectra of a hidden window since it was hidden, announces them and keeps it hidden", async () => {
        select(XRF_ITEM, MATERIAL);
        const view = await mountView();
        await windowOf(view, `auto:xy:${XRF}`)
            .find('[data-action="close"]')
            .trigger("click");
        await flushPromises();
        await hiddenEntries(view);
        expect(view.find(".hidden-windows .badge").exists()).toBe(false);
        select(XRF_OTHER_ITEM);
        await flushPromises();
        expect(windowIds(view)).toEqual(["auto:characterizations"]);
        expect(announce).toHaveBeenLastCalledWith(
            "XRF — energy / counts: 1 spectrum added while the window was hidden.",
        );
        expect(view.find(".hidden-windows .badge").text()).toBe(
            "1 spectrum added",
        );
        select(XRF_THIRD_ITEM);
        await flushPromises();
        expect(announce).toHaveBeenLastCalledWith(
            "XRF — energy / counts: 2 spectra added while the window was hidden.",
        );
        expect(view.find(".hidden-windows .badge").text()).toBe(
            "2 spectra added",
        );
        useExplorerStore().removeFromBasket(XRF_OTHER_ITEM.key);
        useExplorerStore().removeFromBasket(XRF_THIRD_ITEM.key);
        await flushPromises();
        expect(view.find(".hidden-windows .badge").exists()).toBe(false);
        select(XRF_OTHER_ITEM);
        await flushPromises();
        const [show] = await hiddenEntries(view);
        expect(show.find(".badge").text()).toBe("1 spectrum added");
        await show.trigger("click");
        await flushPromises();
        await windowOf(view, `auto:xy:${XRF}`)
            .find('[data-action="close"]')
            .trigger("click");
        await flushPromises();
        await hiddenEntries(view);
        expect(view.find(".hidden-windows .badge").exists()).toBe(false);
    });

    it("reads no series twice when an XY window of more than six spectra gains one or comes back", async () => {
        select(XRF_EIGHT_ITEM);
        const view = await mountView();
        const seriesCalls = (): number =>
            fetchMock.mock.calls.filter(([url]) =>
                String(url).startsWith(SERIES_PATH),
            ).length;
        expect(seriesCalls()).toBe(8);
        select(XRF_OTHER_ITEM);
        await flushPromises();
        expect(seriesCalls()).toBe(9);
        await windowOf(view, `auto:xy:${XRF}`)
            .find('[data-action="close"]')
            .trigger("click");
        await flushPromises();
        await (await hiddenEntries(view))[0].trigger("click");
        await flushPromises();
        expect(windowIds(view)).toEqual([`auto:xy:${XRF}`]);
        expect(seriesCalls()).toBe(9);
    });

    it("does not redraw an XY window whose spectra did not change", async () => {
        select(XRF_ITEM);
        await mountView();
        const drawings = plotly.react.mock.calls.length;
        expect(drawings).toBeGreaterThan(0);
        select(MICRO_ITEM);
        await flushPromises();
        expect(plotly.react).toHaveBeenCalledTimes(drawings);
    });

    describe("tools", () => {
        it("reads the synthesis of the Selection once, and offers the tools it has something for", async () => {
            select(XRF_ITEM, MATERIAL);
            const view = await mountView();
            expect(synthesisCalls()).toHaveLength(1);
            await view.find("button.tool-menu-button").trigger("click");
            expect(
                view.findAll('[role="menuitem"]').map((item) => item.text()),
            ).toEqual(["Coverage matrix", "Periodic table", "Folio image"]);
        });

        it("opens a tool in a window at the end, kept with the layout", async () => {
            select(XRF_ITEM);
            const view = await mountView();
            await openTool(view, "periodic");
            expect(windowIds(view)).toEqual([
                `auto:xy:${XRF}`,
                "tool:periodic:-",
            ]);
            expect(
                windowOf(view, "tool:periodic:-").find("h3 .name").text(),
            ).toBe("Periodic table");
            expect(
                windowOf(view, "tool:periodic:-")
                    .find('.grid button[aria-label="Cu, 1"]')
                    .exists(),
            ).toBe(true);
            expect(storedLayout()?.tools).toEqual([
                { kind: "periodic", params: {} },
            ]);
            expect(announce).toHaveBeenCalledWith(
                "New window at the end: Periodic table",
            );
        });

        it("opens the tools of the last visit again, in their places", async () => {
            select(XRF_ITEM);
            const box = { x: 0, y: 5, w: 12, h: 6 };
            window.localStorage.setItem(
                LAYOUT_STORAGE_KEY,
                JSON.stringify({
                    version: 2,
                    boxes: { "tool:coverage:-": box },
                    hidden: [],
                    tools: [{ kind: "coverage", params: {} }],
                }),
            );
            const view = await mountView();
            expect(windowIds(view)).toContain("tool:coverage:-");
            expect(storedLayout()?.boxes["tool:coverage:-"]).toEqual(box);
            expect(
                useExplorerStore().compare.tools.map((tool) => tool.id),
            ).toEqual(["tool:coverage:-"]);
        });

        it("keeps a tool and its place when the Selection changes", async () => {
            select(XRF_ITEM, MATERIAL);
            const view = await mountView();
            await openTool(view, "coverage");
            useExplorerStore().removeFromBasket(MATERIAL.key);
            await flushPromises();
            expect(windowIds(view)).toContain("tool:coverage:-");
            expect(storedLayout()?.boxes).toHaveProperty("tool:coverage:-");
            expect(synthesisCalls()).toHaveLength(2);
        });

        it("closes a tool on « Close », unlike a window arranged from the Selection", async () => {
            select(XRF_ITEM);
            const view = await mountView();
            await openTool(view, "coverage");
            await windowOf(view, "tool:coverage:-")
                .find('[data-action="close"]')
                .trigger("click");
            await flushPromises();
            expect(windowIds(view)).toEqual([`auto:xy:${XRF}`]);
            expect(hiddenButton(view).attributes("aria-disabled")).toBe("true");
            expect(useExplorerStore().compare.tools).toEqual([]);
            expect(storedLayout()?.tools).toBeUndefined();
            expect(storedLayout()?.boxes).not.toHaveProperty("tool:coverage:-");
            expect(announce).toHaveBeenLastCalledWith(
                "Coverage matrix closed.",
            );
        });

        it("gives the focus to « Hidden windows » when the last window shown is a tool closed", async () => {
            select(XRF_ITEM);
            const view = await mountView();
            await openTool(view, "coverage");
            await windowOf(view, `auto:xy:${XRF}`)
                .find('[data-action="close"]')
                .trigger("click");
            await flushPromises();
            await windowOf(view, "tool:coverage:-")
                .find('[data-action="close"]')
                .trigger("click");
            await flushPromises();
            expect(windowIds(view)).toEqual([]);
            expect(document.activeElement).toBe(hiddenButton(view).element);
        });

        it("says how many drafts the tools read while a tool is open", async () => {
            synthesis = { ...SYNTHESIS, unpublishedCount: 2 };
            select(XRF_ITEM);
            const view = await mountView();
            expect(view.find(".draft-banner").exists()).toBe(false);
            await openTool(view, "periodic");
            expect(view.find(".draft-banner").text()).toBe(
                "The tools read 2 drafts, not published yet.",
            );
        });

        it("keeps the last draft count while the next synthesis is read", async () => {
            synthesis = { ...SYNTHESIS, unpublishedCount: 2 };
            select(XRF_ITEM);
            const view = await mountView();
            await openTool(view, "periodic");
            fetchMock.mockImplementation(() => new Promise(() => undefined));
            select(MATERIAL);
            await flushPromises();
            expect(
                windowOf(view, "tool:periodic:-").find(".loading").exists(),
            ).toBe(true);
            expect(view.find(".draft-banner").text()).toBe(
                "The tools read 2 drafts, not published yet.",
            );
        });

        it("keeps the tools open when the windows are rearranged", async () => {
            select(XRF_ITEM);
            const view = await mountView();
            await openTool(view, "periodic");
            await view.find("button.rearrange").trigger("click");
            await flushPromises();
            expect(windowIds(view)).toContain("tool:periodic:-");
            expect(storedLayout()?.tools).toEqual([
                { kind: "periodic", params: {} },
            ]);
        });

        it("links the windows through the selection shown in the toolbar, and clears it on Escape", async () => {
            select(XRF_ITEM);
            const view = await mountView();
            const indicator = view.find(".toolbar .selection-indicator");
            expect(indicator.find(".summary").text()).toBe("No focus");
            await openTool(view, "periodic");
            await windowOf(view, "tool:periodic:-")
                .find('.grid button[aria-label="Cu, 1"]')
                .trigger("click");
            expect(useExplorerStore().compare.selection).toEqual(["el:Cu"]);
            expect(indicator.find(".summary").text()).toBe(
                "1 in focus · 0 related",
            );
            expect(announce).toHaveBeenLastCalledWith("1 in focus · 0 related");
            document.dispatchEvent(
                new KeyboardEvent("keydown", {
                    key: "Escape",
                    cancelable: true,
                }),
            );
            await flushPromises();
            expect(useExplorerStore().compare.selection).toEqual([]);
            expect(indicator.find(".summary").text()).toBe("No focus");
        });

        it("keeps the selection when Escape closes an enlarged window", async () => {
            select(XRF_ITEM);
            const view = await mountView();
            await openTool(view, "periodic");
            await windowOf(view, "tool:periodic:-")
                .find('.grid button[aria-label="Cu, 1"]')
                .trigger("click");
            await windowOf(view, `auto:xy:${XRF}`)
                .find('[data-action="enlarge"]')
                .trigger("click");
            await flushPromises();
            const dialog = document.querySelector("dialog")!;
            expect(dialog.open).toBe(true);
            pressEscape(dialog);
            await flushPromises();
            expect(dialog.open).toBe(false);
            expect(useExplorerStore().compare.selection).toEqual(["el:Cu"]);
        });

        it("names a tool « Tool » over its title and closes it from its « More » menu", async () => {
            select(XRF_ITEM);
            const view = await mountView();
            await openTool(view, "periodic");
            const tool = windowOf(view, "tool:periodic:-");
            expect(tool.find("h3 .kind").text()).toBe("Tool");
            await tool.find('[data-action="more"]').trigger("click");
            await tool.find('[data-action="menu-close"]').trigger("click");
            await flushPromises();
            expect(useExplorerStore().compare.tools).toEqual([]);
        });

        it("shows the folio of a coverage row clicked in every folio image tool, and says so once", async () => {
            const second = {
                ...SYNTHESIS.canvases[0],
                canvas: "https://iiif.example/c2",
                label: "f. 12v",
            };
            synthesis = {
                ...SYNTHESIS,
                coverage: [
                    ...SYNTHESIS.coverage,
                    {
                        ...SYNTHESIS.coverage[0],
                        canvas: second.canvas,
                        label: second.label,
                    },
                ],
                canvases: [...SYNTHESIS.canvases, second],
            };
            const answer = fetchMock.getMockImplementation()!;
            fetchMock.mockImplementation(async (url: string) =>
                url === "/en/api/explorer/items"
                    ? jsonResponse(documentPayload())
                    : answer(url),
            );
            select(XRF_ITEM);
            const view = await mountView();
            await openTool(view, "coverage");
            const rowHeader = () =>
                windowOf(view, "tool:coverage:-").findAll("tbody .folio")[1];
            await rowHeader().trigger("click");
            await flushPromises();
            expect(announce).not.toHaveBeenLastCalledWith(
                expect.stringContaining("folio image"),
            );
            await rowHeader().trigger("click");
            await openTool(view, "folio");
            const folios = () =>
                view
                    .findAll(".folio-tool select")
                    .map(
                        (picker) => (picker.element as HTMLSelectElement).value,
                    );
            expect(folios()).toEqual(["https://iiif.example/c1"]);
            await rowHeader().trigger("click");
            await flushPromises();
            expect(folios()).toEqual(["https://iiif.example/c2"]);
            expect(announce).toHaveBeenLastCalledWith(
                "1 in focus · 0 related. The folio image shows f. 12v.",
            );
        });

        it("drops a selected element that left with the Selection", async () => {
            select(XRF_ITEM);
            const store = useExplorerStore();
            await mountView();
            store.toggleSelection("el:Cu");
            await flushPromises();
            expect(store.compare.selection).toEqual(["el:Cu"]);
            synthesis = { ...SYNTHESIS, elements: [] };
            select(MATERIAL);
            await flushPromises();
            expect(store.compare.selection).toEqual([]);
            expect(announce).toHaveBeenCalledWith(
                "1 node in focus is no longer linked to the Selection and left the focus.",
            );
        });
    });
});
