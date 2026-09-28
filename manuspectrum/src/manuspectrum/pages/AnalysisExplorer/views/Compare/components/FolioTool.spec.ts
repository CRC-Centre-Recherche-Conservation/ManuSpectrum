import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import L from "leaflet";
import { ref } from "vue";
import { createPinia, setActivePinia } from "pinia";

import FolioTool from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FolioTool.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import {
    FOLIO_REQUEST_KEY,
    LINKED_SELECTION_KEY,
    WINDOW_RESIZE_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    characterization,
    documentPayload,
    label,
    technique,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    sizedContainer,
    stubIiifLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";
import {
    AN1,
    AN2,
    CH1,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";
import {
    analysisNode,
    elementNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { DocumentPayload } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";

vi.hoisted(() => {
    // jsdom's SVG has no createSVGRect: without it Leaflet has no path renderer.
    (
        SVGSVGElement.prototype as unknown as { createSVGRect: () => object }
    ).createSVGRect = () => ({});
});
vi.mock("leaflet-iiif", () => ({}));
vi.mock("utils/leaflet-stack", () => ({ stackSmallestOnTop: vi.fn() }));
vi.mock("@/arches/utils/generate-arches-url.ts", () => ({
    generateArchesURL: (_name: string, parameters: Record<string, string>) =>
        `/en/api/explorer/document/${parameters.resourceid}`,
}));

const C1 = "https://iiif.example/c1";
const C2 = "https://iiif.example/c2";
const XRF_URI = "http://example.org/xrf";
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
    techniques: { [XRF_URI]: technique(XRF_URI, "XRF") },
    analyses: [
        {
            id: uuid(101),
            name: label("MS1_XRF_01"),
            technique: XRF_URI,
            dataKind: "xy",
            unpublished: false,
            zones: [
                {
                    canvas: 0,
                    shape: { type: "rect", x: 10, y: 10, w: 100, h: 100 },
                    feature: "f1",
                },
            ],
        },
        {
            id: uuid(102),
            name: label("MS1_XRF_02"),
            technique: XRF_URI,
            dataKind: "xy",
            unpublished: false,
            zones: [
                {
                    canvas: 1,
                    shape: { type: "point", x: 300, y: 300 },
                    feature: "f2",
                },
            ],
        },
    ],
    characterizations: [
        characterization(1, {
            zone: {
                canvas: C1,
                shape: { type: "point", x: 500, y: 500 },
                source: "own",
            },
        }),
    ],
});
const CANVASES = [
    {
        canvas: C1,
        label: "f. 12r",
        document: uuid(1),
        selected: true,
        analyses: [],
        materials: [],
    },
    {
        canvas: C2,
        label: "f. 12v",
        document: uuid(1),
        selected: true,
        analyses: [],
        materials: [],
    },
];
const SLOTS = new Map([
    [uuid(101), [0]],
    [uuid(102), [9]],
    [uuid(501), [2]],
]);

let fetchMock: ReturnType<typeof vi.fn>;
let iiif: ReturnType<typeof stubIiifLayer>;
let wrapper: VueWrapper | null = null;

beforeEach(() => {
    setActivePinia(createPinia());
    forgetPayloads();
    iiif = stubIiifLayer();
    fetchMock = vi.fn(async () => jsonResponse(DOCUMENT));
    vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
    vi.unstubAllGlobals();
});

async function mountTool(slots = SLOTS): Promise<VueWrapper> {
    wrapper = mount(FolioTool, {
        attachTo: sizedContainer(),
        props: { canvases: CANVASES, slots },
        global: { provide: { [WINDOW_RESIZE_KEY as symbol]: ref(0) } },
    });
    await flushPromises();
    return wrapper;
}

function listed(view: VueWrapper): string[][] {
    return view
        .findAll(".marks li")
        .map((item) =>
            [".slot", ".code", ".name", ".kind"].flatMap((part) =>
                item.find(part).exists() ? [item.find(part).text()] : [],
            ),
        );
}

describe("FolioTool", () => {
    it("fits the whole page to its stage again when the window changes size, until the reader moves the view", async () => {
        const fit = vi.fn();
        (L.tileLayer as unknown as { iiif: unknown }).iiif = vi.fn(() =>
            Object.assign(L.layerGroup(), {
                _imageSizes: [{}],
                _fitBounds: fit,
            }),
        );
        const tick = ref(0);
        wrapper = mount(FolioTool, {
            attachTo: sizedContainer(),
            props: { canvases: CANVASES, slots: SLOTS },
            global: { provide: { [WINDOW_RESIZE_KEY as symbol]: tick } },
        });
        await flushPromises();
        tick.value += 1;
        await flushPromises();
        expect(fit).toHaveBeenCalledTimes(1);
        await wrapper.find(".surface").trigger("pointerdown");
        tick.value += 1;
        await flushPromises();
        expect(fit).toHaveBeenCalledTimes(1);
        await wrapper.find('[data-action="whole-page"]').trigger("click");
        expect(fit).toHaveBeenCalledTimes(2);
        tick.value += 1;
        await flushPromises();
        expect(fit).toHaveBeenCalledTimes(3);
    });

    it("opens on the first canvas placed and reads its document once", async () => {
        const view = await mountTool();
        const picker = view.find("select");
        expect(picker.findAll("option").map((option) => option.text())).toEqual(
            ["f. 12r", "f. 12v"],
        );
        expect((picker.element as HTMLSelectElement).value).toBe(C1);
        expect(fetchMock).toHaveBeenCalledTimes(1);
        expect(String(fetchMock.mock.calls[0][0])).toBe(
            `/en/api/explorer/document/${uuid(1)}`,
        );
        expect(iiif).toHaveBeenCalledWith(
            "https://iiif.example/image/c1/info.json",
            expect.anything(),
        );
    });

    it("marks the Selection's items on the canvas with their A-labels", async () => {
        const view = await mountTool();
        expect(listed(view)).toEqual([
            ["A1", "XRF", "MS1_XRF_01"],
            ["A3", "Characterization 1", "Identified material"],
        ]);
        expect(
            view.findAll(".folio-tool-marker").map((marker) => marker.text()),
        ).toEqual(["A1", "A3"]);
        expect(view.findAll(".folio-tool-frame")).toHaveLength(1);
    });

    it("frames a zone in its slot colour over a halo", async () => {
        const view = await mountTool();
        const halo = view.find("path.folio-tool-halo");
        const frame = view.find("path.folio-tool-frame");
        expect(frame.classes()).toContain("slot-1");
        expect(view.findAll("path.folio-tool-halo")).toHaveLength(1);
        expect(Number(halo.attributes("stroke-width"))).toBeGreaterThan(
            Number(frame.attributes("stroke-width")),
        );
    });

    it("draws every halo under every frame", async () => {
        const [first, second] = DOCUMENT.analyses;
        fetchMock.mockImplementation(async () =>
            jsonResponse({
                ...DOCUMENT,
                analyses: [
                    first,
                    {
                        ...second,
                        zones: [
                            {
                                canvas: 0,
                                shape: {
                                    type: "rect",
                                    x: 50,
                                    y: 50,
                                    w: 100,
                                    h: 100,
                                },
                                feature: "f2",
                            },
                        ],
                    },
                ],
            }),
        );
        const view = await mountTool();
        expect(
            view
                .findAll(".surface path")
                .map((path) =>
                    path.classes("folio-tool-halo") ? "halo" : "frame",
                ),
        ).toEqual(["halo", "halo", "frame", "frame"]);
    });

    it("sizes and centres a marker on the width of its label", async () => {
        const view = await mountTool(
            new Map([
                [uuid(101), [0, 11]],
                [uuid(501), [2]],
            ]),
        );
        const [wide, narrow] = view
            .findAll(".folio-tool-marker-host")
            .map((host) => host.element as HTMLElement);
        expect(wide.textContent).toBe("A1 A12");
        const width = Number.parseFloat(wide.style.width);
        expect(width).toBeGreaterThan(Number.parseFloat(narrow.style.width));
        expect(wide.style.marginLeft).toBe(`${-width / 2}px`);
        expect(narrow.style.width).toBe("28px");
    });

    it("shows another canvas when it is picked, without reading the document again", async () => {
        const view = await mountTool();
        await view.find("select").setValue(C2);
        await flushPromises();
        expect(listed(view)).toEqual([["A10", "XRF", "MS1_XRF_02"]]);
        expect(view.find(".no-image").text()).toBe("No image for this page.");
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it("fits the whole page from an icon button named by its tooltip", async () => {
        const view = await mountTool();
        const whole = view.find('[data-action="whole-page"]');
        expect(whole.find("svg.icon").exists()).toBe(true);
        expect(whole.text()).toBe("");
        expect(
            document.getElementById(whole.attributes("aria-labelledby")!)
                ?.textContent,
        ).toBe("Whole page");
        expect(view.find("button.whole").exists()).toBe(false);
    });

    it("steps to the previous or next folio from buttons beside the picker, each unavailable at its end", async () => {
        const view = await mountTool();
        const previous = () => view.find('[data-action="previous-folio"]');
        const next = () => view.find('[data-action="next-folio"]');
        const picked = () =>
            (view.find("select").element as HTMLSelectElement).value;
        const name = (button: ReturnType<typeof previous>) =>
            document.getElementById(button.attributes("aria-labelledby")!)
                ?.textContent;
        expect(name(previous())).toBe("Previous folio");
        expect(name(next())).toBe("Next folio");
        expect(previous().attributes("aria-disabled")).toBe("true");
        expect(next().attributes("aria-disabled")).toBeUndefined();
        await next().trigger("click");
        await flushPromises();
        expect(picked()).toBe(C2);
        expect(listed(view)).toEqual([["A10", "XRF", "MS1_XRF_02"]]);
        expect(next().attributes("aria-disabled")).toBe("true");
        await next().trigger("click");
        expect(picked()).toBe(C2);
        await previous().trigger("click");
        await flushPromises();
        expect(picked()).toBe(C1);
    });

    it("shows the folio Compare asks for when it has it, the same folio asked again included", async () => {
        const asked = ref<{ canvas: string; count: number } | null>(null);
        wrapper = mount(FolioTool, {
            attachTo: sizedContainer(),
            props: { canvases: CANVASES, slots: SLOTS },
            global: {
                provide: {
                    [WINDOW_RESIZE_KEY as symbol]: ref(0),
                    [FOLIO_REQUEST_KEY as symbol]: { asked, show: vi.fn() },
                },
            },
        });
        await flushPromises();
        const picked = () =>
            (wrapper!.find("select").element as HTMLSelectElement).value;
        asked.value = { canvas: C2, count: 1 };
        await flushPromises();
        expect(picked()).toBe(C2);
        await wrapper.find("select").setValue(C1);
        asked.value = { canvas: C2, count: 2 };
        await flushPromises();
        expect(picked()).toBe(C2);
        asked.value = { canvas: "https://iiif.example/other", count: 3 };
        await flushPromises();
        expect(picked()).toBe(C2);
    });

    it("offers a retry when the document cannot be read", async () => {
        fetchMock.mockImplementationOnce(async () =>
            jsonResponse({ error: "down" }, 500),
        );
        const view = await mountTool();
        expect(view.find(".unavailable-state").exists()).toBe(true);
        await view.find(".unavailable-state .retry").trigger("click");
        await flushPromises();
        expect(listed(view)).toHaveLength(2);
    });

    it("takes the map down with its page when the window closes", async () => {
        iiif = stubIiifLayer({ laid: true });
        const view = await mountTool();
        const page = iiif.mock.results[0].value;
        const removeLayer = vi.spyOn(L.Map.prototype, "removeLayer");
        const removeMap = vi.spyOn(L.Map.prototype, "remove");
        view.unmount();
        wrapper = null;
        const pageRemoved = removeLayer.mock.calls.findIndex(
            ([layer]) => layer === page,
        );
        expect(pageRemoved).toBeGreaterThanOrEqual(0);
        expect(removeMap).toHaveBeenCalledTimes(1);
        expect(removeLayer.mock.invocationCallOrder[pageRemoved]).toBeLessThan(
            removeMap.mock.invocationCallOrder[0],
        );
        removeLayer.mockRestore();
        removeMap.mockRestore();
    });

    describe("with the linked selection", () => {
        const LINKED_CANVASES = [
            { ...CANVASES[0], analyses: [AN1], materials: [CH1] },
            { ...CANVASES[1], analyses: [AN2], materials: [] },
        ];
        let stopLinked: (() => void) | null = null;

        async function mountLinked(): Promise<{
            view: VueWrapper;
            linked: LinkedSelection;
        }> {
            const started = startLinkedSelection();
            stopLinked = started.stop;
            wrapper = mount(FolioTool, {
                attachTo: sizedContainer(),
                props: { canvases: LINKED_CANVASES, slots: SLOTS },
                global: {
                    provide: {
                        [WINDOW_RESIZE_KEY as symbol]: ref(0),
                        [LINKED_SELECTION_KEY as symbol]: started.linked,
                    },
                },
            });
            await flushPromises();
            return { view: wrapper, linked: started.linked };
        }

        function hosts(view: VueWrapper, name: string): (string | undefined)[] {
            return view
                .findAll(".folio-tool-marker-host")
                .map((host) => (host.element as HTMLElement).dataset[name]);
        }

        afterEach(() => {
            stopLinked?.();
            stopLinked = null;
            vi.useRealTimers();
            vi.restoreAllMocks();
        });

        it("restyles the layers drawn on a selection change, without drawing or reading anything again", async () => {
            const { view, linked } = await mountLinked();
            const geoJSON = vi.spyOn(L, "geoJSON");
            const marker = vi.spyOn(L, "marker");
            const layerGroup = vi.spyOn(L, "layerGroup");
            const setStyle = vi.spyOn(L.GeoJSON.prototype, "setStyle");
            linked.toggle(analysisNode(AN2));
            await flushPromises();
            expect(setStyle).toHaveBeenCalled();
            expect(geoJSON).not.toHaveBeenCalled();
            expect(marker).not.toHaveBeenCalled();
            expect(layerGroup).not.toHaveBeenCalled();
            expect(fetchMock).toHaveBeenCalledTimes(1);
            expect(hosts(view, "rel")).toEqual(["none", "none"]);
            expect(
                Number(
                    view
                        .find("path.folio-tool-frame")
                        .attributes("stroke-opacity"),
                ),
            ).toBe(0.35);
        });

        it("draws a linked frame solid and heavier, and marks the markers and the list by level", async () => {
            const { view, linked } = await mountLinked();
            const frame = () => view.find("path.folio-tool-frame");
            expect(frame().attributes("stroke-dasharray")).toBe("4 4");
            expect(hosts(view, "rel")).toEqual([undefined, undefined]);
            linked.toggle(elementNode("Fe"));
            await flushPromises();
            expect(frame().attributes("stroke-dasharray")).toBeUndefined();
            expect(Number(frame().attributes("stroke-width"))).toBe(3);
            expect(hosts(view, "rel")).toEqual(["direct", "evidence"]);
            expect(
                view
                    .findAll(".marks li")
                    .map((item) => item.attributes("data-rel")),
            ).toEqual(["direct", "evidence"]);
        });

        it("selects a record from its name in the list", async () => {
            const { view } = await mountLinked();
            const name = view.findAll(".marks button.name")[1];
            await name.trigger("click");
            expect(useExplorerStore().compare.selection).toEqual([`ch:${CH1}`]);
            expect(name.attributes("aria-pressed")).toBe("true");
            expect(hosts(view, "rel")).toEqual(["evidence", "self"]);
        });

        it("frames the linked marks of the page on « Fit to related »", async () => {
            const { view, linked } = await mountLinked();
            expect(view.find(".related").exists()).toBe(false);
            linked.toggle(elementNode("Fe"));
            await flushPromises();
            const fitBounds = vi.spyOn(L.Map.prototype, "fitBounds");
            await view.find(".related .fit").trigger("click");
            expect(fitBounds).toHaveBeenCalledTimes(1);
        });

        it("names the other folios the selection links and shows one on demand", async () => {
            const { view, linked } = await mountLinked();
            linked.toggle(analysisNode(AN2));
            await flushPromises();
            const name = linked.labelOf(analysisNode(AN2))!.value;
            expect(view.find(".elsewhere > span").text()).toBe(
                `${name} appears on f. 12v.`,
            );
            expect(view.find(".related .fit").exists()).toBe(false);
            await view.find(".elsewhere .show").trigger("click");
            await flushPromises();
            expect(
                (view.find("select").element as HTMLSelectElement).value,
            ).toBe(C2);
            expect(view.find(".elsewhere").exists()).toBe(false);
            expect(fetchMock).toHaveBeenCalledTimes(1);
        });

        it("says a linked record also appears elsewhere when the page holds linked marks too", async () => {
            const { view, linked } = await mountLinked();
            linked.toggle(analysisNode(AN1));
            linked.toggle(analysisNode(AN2));
            await flushPromises();
            expect(view.find(".elsewhere > span").text()).toBe(
                "The selection also appears on f. 12v.",
            );
        });

        it("previews a record under the mouse on its marker and line, fading nothing", async () => {
            vi.useFakeTimers();
            const { view } = await mountLinked();
            await view
                .findAll(".marks li")[0]
                .trigger("pointerenter", { pointerType: "mouse" });
            vi.runAllTimers();
            await flushPromises();
            expect(hosts(view, "preview")).toEqual(["self", "evidence"]);
            expect(hosts(view, "rel")).toEqual([undefined, undefined]);
            expect(
                view
                    .find("path.folio-tool-frame")
                    .attributes("stroke-dasharray"),
            ).toBe("1 3");
        });
    });
});
