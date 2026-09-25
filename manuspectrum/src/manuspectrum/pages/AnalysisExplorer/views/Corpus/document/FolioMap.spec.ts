import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

beforeEach(() => {
    iiif = stubIiifLayer();
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
});
