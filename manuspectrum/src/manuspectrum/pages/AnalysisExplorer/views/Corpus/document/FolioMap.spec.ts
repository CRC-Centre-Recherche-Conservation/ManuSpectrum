import { flushPromises, mount } from "@vue/test-utils";
import L from "leaflet";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import FolioMap from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/FolioMap.vue";

import { techniqueStyles } from "@/manuspectrum/pages/AnalysisExplorer/folio/techniques.ts";
import {
    annotation,
    characterization,
    documentPayload,
    label,
    uuid,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { jsonResponse } from "@/manuspectrum/pages/AnalysisExplorer/testing/responses.ts";
import {
    sizedContainer,
    stubIiifLayer,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";

vi.hoisted(() => {
    // jsdom's SVG has no createSVGRect: without it Leaflet has no path renderer.
    (
        SVGSVGElement.prototype as unknown as { createSVGRect: () => object }
    ).createSVGRect = () => ({});
});
vi.mock("leaflet-iiif", () => ({}));
vi.mock("utils/leaflet-stack", () => ({ stackSmallestOnTop: vi.fn() }));

const LAYERS = { points: true, zones: true, characterizations: true };

function canvasWithImage() {
    const canvas = documentPayload().canvases[0];
    return {
        ...canvas,
        image: {
            service: "https://iiif.example/image/f12r",
            url: null,
            width: 4000,
            height: 6000,
        },
    };
}

function canvasFrom(service: string) {
    return {
        ...canvasWithImage(),
        id: `${service}/canvas`,
        image: { service, url: null, width: 4000, height: 6000 },
    };
}

function infoJson(service: string) {
    return {
        "@context": "http://iiif.io/api/image/2/context.json",
        "@id": service,
        width: 4000,
        height: 6000,
        profile: ["http://iiif.io/api/image/2/level1.json"],
        tiles: [{ width: 256, scaleFactors: [1, 2, 4, 8, 16] }],
    };
}

let realIiifFactory: typeof L.tileLayer.iiif | null = null;

/** The real leaflet-iiif 3.0.0 over a `fetch` that answers each info.json as `answer` says. */
async function realIiif(
    answer: (url: string) => Promise<Response>,
): Promise<ReturnType<typeof vi.fn>> {
    vi.stubGlobal("fetch", vi.fn(answer));
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    if (!realIiifFactory) {
        await vi.importActual("leaflet-iiif");
        realIiifFactory = L.tileLayer.iiif;
    }
    const real = realIiifFactory;
    const factory = vi.fn((...args: Parameters<typeof real>) => real(...args));
    L.tileLayer.iiif = factory as unknown as typeof real;
    return factory;
}

function pageLayers(wrapper: { element: Element }): number {
    return wrapper.element.querySelectorAll(".leaflet-tile-pane .leaflet-layer")
        .length;
}

function mountFolio(props: Record<string, unknown> = {}) {
    const annotations = [
        annotation(1),
        annotation(2, { shape: { type: "point", x: 3000, y: 3000 } }),
    ];
    return mount(FolioMap, {
        attachTo: sizedContainer(),
        props: {
            canvas: canvasWithImage(),
            annotations,
            characterizations: [],
            styles: techniqueStyles(
                annotations.map((entry) => entry.technique),
                label("Analysis"),
            ),
            focus: null,
            slots: new Map<string, string[]>(),
            lit: null,
            dimmedMaterials: new Set<string>(),
            layers: LAYERS,
            ...props,
        },
    });
}

let iiif: ReturnType<typeof stubIiifLayer>;
let sideBySide: ReturnType<typeof vi.fn>;

beforeEach(() => {
    iiif = stubIiifLayer();
    sideBySide = vi.fn(() => ({
        addTo: vi.fn().mockReturnThis(),
        on: vi.fn().mockReturnThis(),
        remove: vi.fn(),
        setRightLayers: vi.fn().mockReturnThis(),
        _range: document.createElement("input"),
    }));
    L.control.sideBySide = sideBySide as unknown as typeof L.control.sideBySide;
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
});

describe("FolioMap", () => {
    it("lays the page from its IIIF image service", async () => {
        const wrapper = mountFolio();
        await flushPromises();
        expect(iiif).toHaveBeenCalledWith(
            "https://iiif.example/image/f12r/info.json",
            expect.objectContaining({ fitBounds: true }),
        );
        wrapper.unmount();
    });

    it("draws one marker per analysis with its technique code and A-label", async () => {
        const wrapper = mountFolio({ slots: new Map([[uuid(101), ["A3"]]]) });
        await flushPromises();
        const markers = wrapper.findAll("[data-target]");
        expect(markers).toHaveLength(2);
        expect(markers[0].text()).toContain("X");
        expect(wrapper.find(`#folio-marker-${uuid(101)}`).text()).toContain(
            "A3",
        );
        wrapper.unmount();
    });

    it("moves between markers with the arrow keys from a single tab stop", async () => {
        const wrapper = mountFolio();
        await flushPromises();
        const stops = wrapper
            .findAll("[data-target]")
            .filter((marker) => marker.attributes("tabindex") === "0");
        expect(stops).toHaveLength(1);
        await stops[0].trigger("keydown", { key: "ArrowRight" });
        const next = wrapper
            .findAll("[data-target]")
            .find((marker) => marker.attributes("tabindex") === "0")!;
        expect(next.attributes("data-target")).not.toBe(
            stops[0].attributes("data-target"),
        );
        expect(document.activeElement).toBe(next.element);
        await next.trigger("keydown", { key: "Enter" });
        expect(wrapper.emitted("select")?.[0]).toEqual([
            { kind: "analysis", id: next.attributes("data-target") },
        ]);
        wrapper.unmount();
    });

    it("gives the keyboard focus back to the marker of an analysis", async () => {
        const wrapper = mountFolio();
        await flushPromises();
        (
            wrapper.vm as unknown as { focusTarget: (id: string) => void }
        ).focusTarget(uuid(102));
        const marker = wrapper.find(`#folio-marker-${uuid(102)}`);
        expect(document.activeElement).toBe(marker.element);
        expect(marker.attributes("tabindex")).toBe("0");
        wrapper.unmount();
    });

    it("dims the analyses the filters drop and lights the evidence of an open identified material", async () => {
        const annotations = [
            annotation(1, { match: false }),
            annotation(2, { shape: { type: "point", x: 3000, y: 3000 } }),
        ];
        const wrapper = mountFolio({ annotations, lit: new Set([uuid(102)]) });
        await flushPromises();
        expect(wrapper.find(`#folio-marker-${uuid(101)}`).classes()).toContain(
            "is-dimmed",
        );
        expect(wrapper.find(`#folio-marker-${uuid(102)}`).classes()).toContain(
            "is-lit",
        );
        wrapper.unmount();
    });

    it("marks a draft analysis", async () => {
        const wrapper = mountFolio({
            annotations: [annotation(1, { unpublished: true })],
        });
        await flushPromises();
        expect(
            wrapper.find(`#folio-marker-${uuid(101)}`).attributes("aria-label"),
        ).toContain("Draft");
        wrapper.unmount();
    });

    it("hides the point markers when the points layer is off", async () => {
        const wrapper = mountFolio({ layers: { ...LAYERS, points: false } });
        await flushPromises();
        expect(wrapper.findAll("[data-target]")).toHaveLength(0);
        wrapper.unmount();
    });

    it("frames an imaging zone and keeps a marker at its centre", async () => {
        const zone = annotation(3, {
            dataKind: "chemical-imaging",
            shape: { type: "rect", x: 100, y: 100, w: 800, h: 400 },
        });
        const wrapper = mountFolio({ annotations: [zone] });
        await flushPromises();
        expect(wrapper.findAll("path.folio-frame")).toHaveLength(1);
        expect(wrapper.find(`#folio-marker-${uuid(103)}`).exists()).toBe(true);
        wrapper.unmount();
    });

    it("hatches the zone of an identified material and opens it on click", async () => {
        const summary = characterization(1, {
            zone: {
                canvas: "https://iiif.example/c1",
                shape: { type: "rect", x: 10, y: 10, w: 300, h: 300 },
                source: "own",
            },
        });
        const wrapper = mountFolio({ characterizations: [summary] });
        await flushPromises();
        const zone = wrapper.find("path.folio-material");
        expect(zone.exists()).toBe(true);
        await zone.trigger("click");
        expect(wrapper.emitted("select")?.at(-1)).toEqual([
            { kind: "characterization", id: summary.id },
        ]);
        wrapper.unmount();
    });

    it("labels an identified material as text, never as markup", async () => {
        const markup = '<img src="x" class="injected">';
        const summary = characterization(1, {
            materials: [
                {
                    value: valueRef("http://example.org/m", markup),
                    confidence: null,
                    proportion: null,
                },
            ],
            zone: {
                canvas: "https://iiif.example/c1",
                shape: { type: "rect", x: 10, y: 10, w: 300, h: 300 },
                source: "own",
            },
        });
        const wrapper = mountFolio({ characterizations: [summary] });
        await flushPromises();
        const tooltip = wrapper.find(".folio-material-label");
        expect(tooltip.text()).toBe(markup);
        expect(wrapper.find("img.injected").exists()).toBe(false);
        wrapper.unmount();
    });

    it("shows the no-image state when the canvas has no image service", async () => {
        const canvas = {
            ...canvasWithImage(),
            image: { service: null, url: null, width: 1, height: 1 },
        };
        const wrapper = mountFolio({ canvas });
        await flushPromises();
        expect(wrapper.text()).toContain("No image for this page");
        expect(iiif).not.toHaveBeenCalled();
        expect(wrapper.findAll("[data-target]")).toHaveLength(2);
        wrapper.unmount();
    });

    it("lays an imaging layer at its opacity and puts it under the curtain", async () => {
        const overlay = {
            key: "a:0",
            url: "https://iiif.example/pb/full/!2048,2048/0/default.jpg",
            bounds: [
                [-1, 0],
                [0, 2],
            ] as [[number, number], [number, number]],
            opacity: 0.5,
            label: "Pb",
        };
        const wrapper = mountFolio({ overlays: [overlay] });
        await flushPromises();
        const image = wrapper.find("img.folio-overlay");
        expect(image.attributes("src")).toBe(overlay.url);
        expect((image.element as HTMLElement).style.opacity).toBe("0.5");
        await wrapper.setProps({ curtain: "a:0" });
        expect(sideBySide).toHaveBeenCalledWith([], expect.anything());
        wrapper.unmount();
    });

    describe("with the real leaflet-iiif", () => {
        it("follows later page changes and unmounts while an info.json never answers", async () => {
            const factory = await realIiif(() => new Promise(() => undefined));
            const wrapper = mountFolio({
                canvas: canvasFrom("https://dead.example/a"),
            });
            await flushPromises();
            await wrapper.setProps({
                canvas: canvasFrom("https://dead.example/b"),
            });
            await wrapper.setProps({
                canvas: canvasFrom("https://dead.example/c"),
            });
            await flushPromises();
            expect(factory.mock.calls.map(([url]) => url)).toEqual([
                "https://dead.example/a/info.json",
                "https://dead.example/b/info.json",
                "https://dead.example/c/info.json",
            ]);
            expect(() => wrapper.unmount()).not.toThrow();
        });

        it("lays the next page after an image host that refuses its info.json", async () => {
            await realIiif(async (url) =>
                url.startsWith("https://dead.example")
                    ? Promise.reject(new TypeError("Failed to fetch"))
                    : jsonResponse(infoJson(url.replace("/info.json", ""))),
            );
            const wrapper = mountFolio({
                canvas: canvasFrom("https://dead.example/a"),
            });
            await flushPromises();
            await wrapper.setProps({
                canvas: canvasFrom("https://iiif.example/b"),
            });
            await flushPromises();
            expect(pageLayers(wrapper)).toBe(1);
            expect(() => wrapper.unmount()).not.toThrow();
        });

        it("never lays a page left before its info.json arrived", async () => {
            let answerFirst: () => void = () => undefined;
            await realIiif(
                (url) =>
                    new Promise((resolve) => {
                        const response = jsonResponse(
                            infoJson(url.replace("/info.json", "")),
                        );
                        if (url.includes("/a/")) {
                            answerFirst = () => resolve(response);
                        } else {
                            resolve(response);
                        }
                    }),
            );
            const wrapper = mountFolio({
                canvas: canvasFrom("https://slow.example/a"),
            });
            await flushPromises();
            await wrapper.setProps({
                canvas: canvasFrom("https://iiif.example/b"),
            });
            await flushPromises();
            answerFirst();
            await flushPromises();
            expect(pageLayers(wrapper)).toBe(1);
            wrapper.unmount();
        });
    });

    describe("with marker groups", () => {
        const NEAR = [
            annotation(1, { shape: { type: "point", x: 100, y: 100 } }),
            annotation(2, { shape: { type: "point", x: 300, y: 100 } }),
        ];
        const SAME_SPOT = [
            annotation(1, { shape: { type: "point", x: 100, y: 100 } }),
            annotation(2, { shape: { type: "point", x: 100, y: 100 } }),
        ];
        /** markercluster animates its regrouping with timeouts (jsdom has CSS transitions). */
        async function afterRegrouping(): Promise<void> {
            await vi.advanceTimersByTimeAsync(1000);
            await flushPromises();
        }

        beforeEach(() => {
            vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
        });

        afterEach(() => {
            vi.useRealTimers();
        });

        const NO_IMAGE = {
            ...canvasWithImage(),
            image: { service: null, url: null, width: 1, height: 1 },
        };

        it("keeps the folio a single tab stop when markers are grouped", async () => {
            const wrapper = mountFolio({ annotations: NEAR });
            await flushPromises();
            expect(wrapper.find(".folio-cluster").exists()).toBe(true);
            expect(wrapper.findAll('.folio [tabindex="0"]')).toHaveLength(1);
            wrapper.unmount();
        });

        it("zooms into a group from the keyboard and focuses its first marker", async () => {
            const wrapper = mountFolio({ annotations: NEAR });
            await afterRegrouping();
            await wrapper.find(".folio-cluster").trigger("keydown", {
                key: "Enter",
            });
            await afterRegrouping();
            expect(wrapper.find(".folio-cluster").exists()).toBe(false);
            const focused = document.activeElement as HTMLElement;
            expect(focused.dataset.target).toBe(uuid(101));
            expect(focused.tabIndex).toBe(0);
            wrapper.unmount();
        });

        it("spreads a group at the last zoom and moves through its markers", async () => {
            const wrapper = mountFolio({
                annotations: SAME_SPOT,
                canvas: NO_IMAGE,
            });
            await afterRegrouping();
            await wrapper.find(".folio-cluster").trigger("keydown", {
                key: "Enter",
            });
            await afterRegrouping();
            const first = document.activeElement as HTMLElement;
            expect(first.classList).toContain("folio-marker");
            first.dispatchEvent(
                new KeyboardEvent("keydown", {
                    key: "ArrowRight",
                    bubbles: true,
                }),
            );
            const second = document.activeElement as HTMLElement;
            expect(second.classList).toContain("folio-marker");
            expect(second.dataset.target).not.toBe(first.dataset.target);
            wrapper.unmount();
        });
    });

    describe("with the curtain", () => {
        function layerOverlay(key: string, opacity = 0.5) {
            return {
                key,
                url: `https://iiif.example/${key}/full/!2048,2048/0/default.jpg`,
                bounds: [
                    [-1, 0],
                    [0, 2],
                ] as [[number, number], [number, number]],
                opacity,
                label: key,
            };
        }

        it("keeps one curtain across opacity changes and layer scrolls", async () => {
            const wrapper = mountFolio({
                overlays: [layerOverlay("a:0")],
                curtain: "a:0",
            });
            await flushPromises();
            await wrapper.setProps({ overlays: [layerOverlay("a:0", 0.8)] });
            await wrapper.setProps({
                overlays: [layerOverlay("a:1", 0.8)],
                curtain: "a:1",
            });
            expect(sideBySide).toHaveBeenCalledTimes(1);
            const control = sideBySide.mock.results[0].value;
            expect(control.remove).not.toHaveBeenCalled();
            expect(control.setRightLayers).toHaveBeenCalled();
            wrapper.unmount();
        });

        it("clips each laid layer through a pane of its own", async () => {
            const wrapper = mountFolio({
                overlays: [layerOverlay("a:0")],
                curtain: "a:0",
            });
            await flushPromises();
            const image = wrapper.find("img.folio-overlay").element;
            const pane = image.parentElement!;
            expect(pane.classList).toContain("leaflet-pane");
            expect(pane.classList).not.toContain("leaflet-overlay-pane");
            const [, under] = sideBySide.mock.calls[0] as unknown as [
                unknown,
                { getContainer: () => HTMLElement },
            ];
            expect(under.getContainer()).toBe(pane);
            wrapper.unmount();
        });

        it("names the curtain's range", async () => {
            const wrapper = mountFolio({
                overlays: [layerOverlay("a:0")],
                curtain: "a:0",
            });
            await flushPromises();
            const control = sideBySide.mock.results[0].value;
            expect(control._range.getAttribute("aria-label")).toBe(
                "Curtain position",
            );
            wrapper.unmount();
        });
    });
});
