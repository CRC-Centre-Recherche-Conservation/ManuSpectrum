import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import L from "leaflet";
import { ref } from "vue";

import FolioTool from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FolioTool.vue";

import { forgetPayloads } from "@/manuspectrum/pages/AnalysisExplorer/api/http.ts";
import { WINDOW_RESIZE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
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
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { DocumentPayload } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

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
                .findAll("path")
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
});
