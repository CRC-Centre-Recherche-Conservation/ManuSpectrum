import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import CompareView from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/CompareView.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisHit,
    characterization,
    fileEntry,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
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
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

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
    generateArchesURL: () => "/en/api/explorer/items",
}));

const XRF = "counts|energy (kev)|asc";
const RAMAN = "intensity|raman shift|asc";
const FORS = "reflectance|wavelength|asc";
const FTIR = "reflectance|wavenumber|desc";

const SERIES_PATH = "/api/spectrum-preview/";

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
    ].map((item) => [item.key, item]),
);

let pinia: Pinia;
let announce: ReturnType<typeof vi.fn>;
let fetchMock: ReturnType<typeof vi.fn>;
let wrapper: VueWrapper | null = null;

beforeEach(() => {
    resetFakeGrids();
    forgetPayloads();
    window.localStorage.clear();
    announce = vi.fn();
    resetPlotly();
    fetchMock = vi.fn(async (url: string) => {
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
    vi.unstubAllGlobals();
});

function select(...items: Item[]): void {
    useExplorerStore().addManyToBasket(items.map((item) => item.key));
}

/** The requests of the items API, the spectra left out. */
function itemCalls(): string[] {
    return fetchMock.mock.calls
        .map(([url]) => String(url))
        .filter((url) => !url.startsWith(SERIES_PATH));
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

function storedLayout(): { boxes: object; hidden: string[] } | null {
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
            view.findAll(".compare-window h3").map((title) => title.text()),
        ).toEqual([
            "Intensity against Raman shift (cm-1)",
            "XRF — energy / counts",
            "Micro-images",
            "Identified materials",
            "Not in a chart",
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
            windowOf(view, "auto:characterizations").find("tbody th").text(),
        ).toBe("Characterization 1");
        expect(windowOf(view, "auto:not-in-chart").find(".reason").text()).toBe(
            "No spectrum, map or image to show.",
        );
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
            "Identified materials hidden. Show it again from « Hidden windows ».",
        );
        expect(storedLayout()?.hidden).toEqual(["auto:characterizations"]);
        expect(view.find(".hidden-windows h3").text()).toBe(
            "Hidden windows (1)",
        );
        const show = view.find(".hidden-windows button");
        expect(show.text()).toBe("Show Identified materials");
        await show.trigger("click");
        await flushPromises();
        expect(windowIds(view)).toEqual([
            `auto:xy:${XRF}`,
            "auto:characterizations",
        ]);
        expect(view.find(".hidden-windows").exists()).toBe(false);
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
        expect(view.find(".hidden-windows button").text()).toBe(
            "Show XRF — energy / counts",
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
        expect(view.find(".hidden-windows").exists()).toBe(false);
    });

    it("brings every hidden window back when the windows are rearranged", async () => {
        select(XRF_ITEM, MATERIAL);
        const view = await mountView();
        await windowOf(view, `auto:xy:${XRF}`)
            .find('[data-action="close"]')
            .trigger("click");
        await flushPromises();
        await view.find("button.rearrange").trigger("click");
        await flushPromises();
        expect(windowIds(view)).toEqual([
            `auto:xy:${XRF}`,
            "auto:characterizations",
        ]);
        expect(view.find(".hidden-windows").exists()).toBe(false);
        expect(announce).toHaveBeenLastCalledWith("Windows rearranged.");
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
        expect(document.activeElement).toBe(
            view.find(".hidden-windows button").element,
        );
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
            version: 2,
            boxes: {},
            hidden: [],
            folded: {},
        });
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

    it("announces new spectra in a hidden window, keeps it hidden and marks it", async () => {
        select(XRF_ITEM, MATERIAL);
        const view = await mountView();
        await windowOf(view, `auto:xy:${XRF}`)
            .find('[data-action="close"]')
            .trigger("click");
        await flushPromises();
        expect(view.find(".hidden-windows .badge").exists()).toBe(false);
        select(XRF_OTHER_ITEM);
        await flushPromises();
        expect(windowIds(view)).toEqual(["auto:characterizations"]);
        expect(announce).toHaveBeenLastCalledWith(
            "XRF — energy / counts: new spectra added to a hidden window",
        );
        const show = view.find(".hidden-windows button");
        expect(show.find(".badge").text()).toBe("new spectra");
        await show.trigger("click");
        await flushPromises();
        await windowOf(view, `auto:xy:${XRF}`)
            .find('[data-action="close"]')
            .trigger("click");
        await flushPromises();
        expect(view.find(".hidden-windows .badge").exists()).toBe(false);
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
});
