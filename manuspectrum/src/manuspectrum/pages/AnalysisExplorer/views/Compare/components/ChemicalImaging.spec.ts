import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import L from "leaflet";
import PrimeVue from "primevue/config";
import { ref } from "vue";
import { createPinia, setActivePinia } from "pinia";

import ChemicalImaging from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ChemicalImaging.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    ANNOUNCE_KEY,
    LINKED_SELECTION_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    analysisHit,
    documentPayload,
    imagingEntry,
    label,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    sizedContainer,
    stubIiifLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";
import {
    AN1,
    ITEMS,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";
import {
    analysisNode,
    elementNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { VueWrapper } from "@vue/test-utils";
import type {
    AnalysisHit,
    DocumentPayload,
    FileEntry,
    FileLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type { MapLine } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

vi.hoisted(() => {
    // jsdom's SVG has no createSVGRect: without it Leaflet has no path renderer.
    (
        SVGSVGElement.prototype as unknown as { createSVGRect: () => object }
    ).createSVGRect = () => ({});
});
vi.mock("leaflet-iiif", () => ({}));
vi.mock("leaflet-side-by-side", () => ({}));
vi.mock("utils/leaflet-stack", () => ({ stackSmallestOnTop: vi.fn() }));
vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (_name: string, parameters: Record<string, string>) =>
        `/en/api/explorer/document/${parameters.resourceid}`,
}));

const REAL_SIDE_BY_SIDE = L.control.sideBySide;
const REAL_IIIF = (L.tileLayer as unknown as { iiif: unknown }).iiif;

const C1 = "https://iiif.example/c1";
const ZONE = { type: "rect" as const, x: 100, y: 100, w: 800, h: 400 };
const DOCUMENT: DocumentPayload = documentPayload({
    canvases: documentPayload().canvases.map((canvas, index) =>
        index === 0
            ? {
                  ...canvas,
                  image: {
                      service: "https://iiif.example/image/c1",
                      url: null,
                      width: 4000,
                      height: 6000,
                  },
              }
            : canvas,
    ),
    analyses: [101, 102].map((n) => ({
        id: uuid(n),
        name: label(`MS1_${n}`),
        technique: null,
        dataKind: "chemical-imaging" as const,
        unpublished: false,
        zones: [{ canvas: 0, shape: ZONE, feature: `f${n}` }],
    })),
});

function layer(
    index: number,
    name: string,
    kind: FileLayer["kind"] = "element",
): FileLayer {
    const value = Number.parseInt(name, 10);
    return {
        index,
        label: name,
        kind,
        element: kind === "element" ? name : null,
        band: kind === "band" ? { value, unit: "nm" } : null,
        image: {
            service: `https://iiif.example/image/${name.replace(" ", "")}`,
            url: null,
            width: 900,
            height: 600,
        },
    };
}

function map(
    slot: number,
    layers: FileLayer[],
    canvas: string | null = C1,
): MapLine {
    const analysis = analysisHit(slot + 1, {
        canvas,
        dataKinds: ["chemical-imaging"],
    });
    return {
        key: `an:${analysis.id}:-`,
        slot,
        analysis,
        file: imagingEntry({ name: `map-${slot + 1}`, layers }),
        named: null,
    };
}

const XRF_MAPS = [
    map(0, [layer(0, "Pb"), layer(1, "Hg")]),
    map(1, [layer(0, "Cu"), layer(1, "Pb")]),
];

let fetchMock: ReturnType<typeof vi.fn>;
let sideBySide: ReturnType<typeof vi.fn>;
let resizeTick = ref(0);
let wrapper: VueWrapper | null = null;

beforeEach(() => {
    setActivePinia(createPinia());
    forgetPayloads();
    stubIiifLayer();
    fetchMock = vi.fn(async () => jsonResponse(DOCUMENT));
    vi.stubGlobal("fetch", fetchMock);
    sideBySide = vi.fn(() => ({
        addTo: vi.fn().mockReturnThis(),
        on: vi.fn().mockReturnThis(),
        remove: vi.fn(),
        setRightLayers: vi.fn().mockReturnThis(),
        _range: document.createElement("input"),
    }));
    L.control.sideBySide = sideBySide as unknown as typeof L.control.sideBySide;
    resizeTick = ref(0);
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    L.control.sideBySide = REAL_SIDE_BY_SIDE;
    (L.tileLayer as unknown as { iiif: unknown }).iiif = REAL_IIIF;
});

async function mountMaps(maps: MapLine[] = XRF_MAPS): Promise<VueWrapper> {
    wrapper = mount(ChemicalImaging, {
        attachTo: sizedContainer(),
        props: { maps },
        global: {
            plugins: [PrimeVue],
            provide: { [WINDOW_RESIZE_KEY as symbol]: resizeTick },
        },
    });
    await flushPromises();
    return wrapper;
}

/** What each map shows: the label of its layer, else what it says of the layer it lacks. */
function shown(view: VueWrapper): string[] {
    return view.findAll(".chemical-imaging-map").map((card) => {
        const note = card.find(".not-mapped .message");
        if (note.exists()) return note.text();
        return card.find(".imaging-preview .current .value").text();
    });
}

function picked(view: VueWrapper): string {
    const picker = view.find(".layer-picker select")
        .element as HTMLSelectElement;
    return picker.selectedOptions[0]?.text.trim() ?? "";
}

async function lay(view: VueWrapper, index: number): Promise<void> {
    await view
        .findAll(".chemical-imaging-map")
        [index].find("input.lay")
        .setValue(true);
    await flushPromises();
}

describe("ChemicalImaging", () => {
    it("shows the maps side by side, each under its slot and name, with one layer control over them", async () => {
        const view = await mountMaps();
        expect(
            view.findAll("figcaption").map((caption) => caption.text()),
        ).toEqual([
            expect.stringMatching(/^A1.*map-1$/),
            expect.stringMatching(/^A2.*map-2$/),
        ]);
        const picker = view.find(".layer-picker");
        expect(picker.find("label").text()).toBe("Element");
        expect(picker.findAll("option").map((option) => option.text())).toEqual(
            ["Pb", "Hg", "Cu"],
        );
        expect(
            view.text().split("Each map keeps its own contrast.").length - 1,
        ).toBe(1);
        expect(view.findAll(".imaging-preview .scroll")).toHaveLength(0);
    });

    it("holds the same layer on every map by default, and says so where a map lacks it", async () => {
        const view = await mountMaps();
        const sync = view.find("input.sync");
        expect((sync.element as HTMLInputElement).checked).toBe(true);
        expect(view.find(".sync").text()).toBe("Same layer on every map");
        expect(shown(view)).toEqual(["Pb", "Pb"]);
        await view.find(".layer-picker select").setValue(1);
        await flushPromises();
        expect(shown(view)).toEqual(["Hg", "No Hg layer for this map"]);
        expect(view.findAll(".not-mapped .held")[0].text()).toBe(
            "Its layers: Cu, Pb",
        );
        await view.find(".layer-picker select").setValue(2);
        await flushPromises();
        expect(shown(view)).toEqual(["No Cu layer for this map", "Cu"]);
    });

    it("reads a document shared by several maps once", async () => {
        await mountMaps();
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("scrolls through the layers of the kind shown only, elements or bands", async () => {
        const view = await mountMaps([
            map(0, [layer(0, "Pb"), layer(1, "Hg")]),
            map(1, [layer(0, "400 nm", "band"), layer(1, "1000 nm", "band")]),
        ]);
        const ends = () =>
            view.findAll(".shared .scroll .ends span").map((end) => end.text());
        expect(ends()).toEqual(["Pb", "Hg"]);
        expect(
            view
                .find(".shared .scroll [role=slider]")
                .attributes("aria-valuetext"),
        ).toBe("Pb, layer 1 of 2");
        view.findComponent({ name: "Slider" }).vm.$emit("update:modelValue", 1);
        await flushPromises();
        expect(shown(view)).toEqual(["Hg", "No Hg layer for this map"]);
        await view.find(".layer-picker select").setValue(3);
        await flushPromises();
        expect(ends()).toEqual(["400 nm", "1000 nm"]);
        view.findComponent({ name: "Slider" }).vm.$emit("update:modelValue", 0);
        await flushPromises();
        expect(shown(view)).toEqual(["No 400 nm layer for this map", "400 nm"]);
    });

    it("scrolls every map through the layers together, saying where the handle is", async () => {
        const view = await mountMaps();
        view.findComponent({ name: "Slider" }).vm.$emit("update:modelValue", 1);
        await flushPromises();
        expect(shown(view)).toEqual(["Hg", "No Hg layer for this map"]);
        expect(picked(view)).toBe("Hg");
        expect(
            view
                .find(".shared .scroll [role=slider]")
                .attributes("aria-valuetext"),
        ).toBe("Hg, layer 2 of 3");
    });

    it("names bands by their kind and sorts them by value", async () => {
        const view = await mountMaps([
            map(0, [layer(0, "650 nm", "band"), layer(1, "400 nm", "band")]),
            map(1, [layer(0, "450 nm", "band")]),
        ]);
        expect(view.find(".layer-picker label").text()).toBe("Band");
        expect(
            view.findAll(".layer-picker option").map((option) => option.text()),
        ).toEqual(["400 nm", "450 nm", "650 nm"]);
        expect(shown(view)).toEqual(["400 nm", "No 400 nm layer for this map"]);
    });

    it("gives each map its own layer scroll once the maps are no longer held together", async () => {
        const view = await mountMaps();
        await view.find(".layer-picker select").setValue(1);
        await view.find("input.sync").setValue(false);
        expect(view.find(".layer-picker").exists()).toBe(false);
        expect(view.findAll(".imaging-preview .scroll")).toHaveLength(2);
        expect(shown(view)).toEqual(["Hg", "Pb"]);
        view.findAllComponents({ name: "Slider" })[1].vm.$emit(
            "update:modelValue",
            0,
        );
        await flushPromises();
        expect(shown(view)).toEqual(["Hg", "Cu"]);
        await view.find("input.sync").setValue(true);
        expect(shown(view)).toEqual(["Hg", "No Hg layer for this map"]);
    });

    it("lays a map on its own page under a curtain of its own, keeping it out of the document screen", async () => {
        const view = await mountMaps();
        expect(view.findAll(".leaflet-container")).toHaveLength(0);
        await lay(view, 0);
        const card = view.findAll(".chemical-imaging-map")[0];
        expect(card.find("img.folio-overlay").attributes("alt")).toBe("Pb");
        expect(card.find("img.layer-image").exists()).toBe(false);
        expect(view.findAll(".leaflet-container")).toHaveLength(1);
        expect(sideBySide).not.toHaveBeenCalled();
        await card.find("input.curtain").setValue(true);
        expect(sideBySide).toHaveBeenCalledTimes(1);
        expect(view.text()).toContain(
            "Indicative positioning, not registered.",
        );
        expect(useExplorerStore().overlays).toEqual({});
    });

    it("carries a laid map to the layer held on every map", async () => {
        const view = await mountMaps();
        await lay(view, 0);
        await view.find(".layer-picker select").setValue(1);
        await flushPromises();
        const card = view.findAll(".chemical-imaging-map")[0];
        expect(card.find("img.folio-overlay").attributes("alt")).toBe("Hg");
    });

    it("shows a map without a zone on a page alone, with nothing to lay it on", async () => {
        const view = await mountMaps([map(0, [layer(0, "Pb")], null)]);
        expect(fetchMock).not.toHaveBeenCalled();
        const card = view.find(".chemical-imaging-map");
        expect(card.find("img.layer-image").attributes("alt")).toBe("Pb");
        expect(card.find("input.lay").attributes("disabled")).toBeDefined();
        expect(card.text()).toContain("no zone on this page");
    });

    it("says when the image server does not give a map, and asks again on Retry", async () => {
        const view = await mountMaps();
        const card = view.findAll(".chemical-imaging-map")[0];
        // The first failure retries once at the layer's own max size (the
        // declared size a bounded request clamps to can itself be stale or
        // wrong); only a second failure is reported.
        await card.find("img.layer-image").trigger("error");
        await card.find("img.layer-image").trigger("error");
        const status = card.find(".unavailable");
        expect(status.text()).toContain("Map unavailable (image server)");
        await status.find("button").trigger("click");
        expect(card.find("img.layer-image").exists()).toBe(true);
    });

    it("says when a laid map is not given, and lays it again on Retry", async () => {
        const view = await mountMaps();
        await lay(view, 0);
        const card = view.findAll(".chemical-imaging-map")[0];
        await card.find("img.folio-overlay").trigger("error");
        await card.find("img.folio-overlay").trigger("error");
        expect(card.find(".unavailable").text()).toContain(
            "Map unavailable (image server)",
        );
        await card.find(".unavailable button").trigger("click");
        await flushPromises();
        expect(card.find("img.folio-overlay").exists()).toBe(true);
    });

    it("draws the laid maps again when the window is resized", async () => {
        const resize = vi.spyOn(L.Map.prototype, "invalidateSize");
        const view = await mountMaps();
        await lay(view, 0);
        await lay(view, 1);
        resize.mockClear();
        resizeTick.value += 1;
        await flushPromises();
        expect(resize).toHaveBeenCalledTimes(2);
    });

    it("takes each laid map down with its page and its curtain when the window closes", async () => {
        const iiif = stubIiifLayer({ laid: true });
        const view = await mountMaps();
        for (const index of [0, 1]) {
            await lay(view, index);
            await view
                .findAll(".chemical-imaging-map")
                [index].find("input.curtain")
                .setValue(true);
        }
        const pages = iiif.mock.results.map((result) => result.value);
        expect(pages).toHaveLength(2);
        const removeLayer = vi.spyOn(L.Map.prototype, "removeLayer");
        const removeMap = vi.spyOn(L.Map.prototype, "remove");
        view.unmount();
        wrapper = null;
        expect(removeMap).toHaveBeenCalledTimes(2);
        const lastMapRemoved = Math.max(...removeMap.mock.invocationCallOrder);
        for (const page of pages) {
            const call = removeLayer.mock.calls.findIndex(
                ([layer]) => layer === page,
            );
            expect(call).toBeGreaterThanOrEqual(0);
            expect(removeLayer.mock.invocationCallOrder[call]).toBeLessThan(
                lastMapRemoved,
            );
        }
        expect(sideBySide).toHaveBeenCalledTimes(2);
        for (const result of sideBySide.mock.results) {
            expect(result.value.remove).toHaveBeenCalled();
        }
    });

    describe("with the linked selection", () => {
        let stopLinked: (() => void) | null = null;
        let announce: ReturnType<typeof vi.fn>;

        async function mountLinked(): Promise<{
            view: VueWrapper;
            linked: LinkedSelection;
        }> {
            announce = vi.fn();
            const started = startLinkedSelection(announce);
            stopLinked = started.stop;
            const first = ITEMS[0] as {
                key: string;
                analysis: AnalysisHit;
                files: FileEntry[];
            };
            const second = ITEMS[1] as { key: string; analysis: AnalysisHit };
            const maps: MapLine[] = [
                {
                    key: first.key,
                    slot: 0,
                    analysis: first.analysis,
                    file: first.files[1],
                    named: null,
                },
                {
                    key: second.key,
                    slot: 1,
                    analysis: second.analysis,
                    file: imagingEntry({
                        name: "map-2",
                        layers: [layer(0, "Cu")],
                    }),
                    named: null,
                },
            ];
            wrapper = mount(ChemicalImaging, {
                attachTo: sizedContainer(),
                props: { maps },
                global: {
                    plugins: [PrimeVue],
                    provide: {
                        [WINDOW_RESIZE_KEY as symbol]: resizeTick,
                        [ANNOUNCE_KEY as symbol]: announce,
                        [LINKED_SELECTION_KEY as symbol]: started.linked,
                    },
                },
            });
            await flushPromises();
            return { view: wrapper, linked: started.linked };
        }

        afterEach(() => {
            stopLinked?.();
            stopLinked = null;
            vi.useRealTimers();
        });

        it("switches the shared layer to an element selected, says so, and brings the previous one back once it is unselected", async () => {
            const { view, linked } = await mountLinked();
            expect(picked(view)).toBe("Fe Ka");
            linked.toggle(elementNode("Pb"));
            await flushPromises();
            expect(picked(view)).toBe("Pb La");
            expect(shown(view)).toEqual([
                "Pb La",
                "No Pb La layer for this map",
            ]);
            expect(announce).toHaveBeenLastCalledWith(
                "1 in focus · 3 related. The chemical imaging maps show Pb La.",
            );
            linked.toggle(elementNode("Pb"));
            await flushPromises();
            expect(picked(view)).toBe("Fe Ka");
            expect(announce).toHaveBeenLastCalledWith(
                "No focus. The chemical imaging maps show Fe Ka again.",
            );
        });

        it("follows the last element selected that a map holds", async () => {
            const { view, linked } = await mountLinked();
            linked.toggle(elementNode("Cu"));
            linked.toggle(elementNode("Zn"));
            await flushPromises();
            expect(picked(view)).toBe("Cu");
            linked.toggle(elementNode("Pb"));
            await flushPromises();
            expect(picked(view)).toBe("Pb La");
        });

        it("follows the element pinned last even when it takes a lower slot", async () => {
            const { view, linked } = await mountLinked();
            linked.toggle(elementNode("Fe"));
            linked.toggle(elementNode("Pb"));
            linked.toggle(elementNode("Fe"));
            await flushPromises();
            expect(picked(view)).toBe("Pb La");
            linked.toggle(elementNode("Cu"));
            await flushPromises();
            expect(linked.slotOf(elementNode("Cu"))).toBe(1);
            expect(picked(view)).toBe("Cu");
        });

        it("keeps the layer the reader picked once the element is unselected", async () => {
            const { view, linked } = await mountLinked();
            linked.toggle(elementNode("Pb"));
            await flushPromises();
            await view.find(".layer-picker select").setValue(2);
            linked.toggle(elementNode("Pb"));
            await flushPromises();
            expect(picked(view)).toBe("Cu");
        });

        it("moves the maps holding a selected element to it while they are not held together", async () => {
            const { view, linked } = await mountLinked();
            await view.find("input.sync").setValue(false);
            linked.toggle(elementNode("Pb"));
            await flushPromises();
            expect(shown(view)).toEqual(["Pb La", "Cu"]);
            expect(announce).toHaveBeenLastCalledWith(
                "1 in focus · 3 related. The chemical imaging maps show Pb La.",
            );
        });

        it("never switches the layer on a preview", async () => {
            vi.useFakeTimers();
            const { view, linked } = await mountLinked();
            linked.preview(elementNode("Pb"), { pointerType: "mouse" });
            vi.runAllTimers();
            await view.vm.$nextTick();
            expect(picked(view)).toBe("Fe Ka");
            expect(
                view.find(".chemical-imaging-map").attributes("data-preview"),
            ).toBe("direct");
        });

        it("marks each map by its analysis and selects it from its name", async () => {
            const { view, linked } = await mountLinked();
            linked.toggle(elementNode("Fe"));
            await flushPromises();
            expect(
                view
                    .findAll(".chemical-imaging-map")
                    .map((card) => card.attributes("data-rel")),
            ).toEqual(["direct", "none"]);
            linked.clear();
            await view
                .find(".chemical-imaging-map button.record")
                .trigger("click");
            expect(useExplorerStore().compare.selection).toEqual([
                analysisNode(AN1),
            ]);
            expect(
                view.find(".chemical-imaging-map").attributes("data-rel"),
            ).toBe("self");
        });
    });
});
