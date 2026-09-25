import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import CanvasStrip from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/document/CanvasStrip.vue";

import { documentPayload } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

describe("CanvasStrip", () => {
    it("shows the analysed pages, marks the current one and changes page", async () => {
        const canvases = documentPayload().canvases;
        const wrapper = mount(CanvasStrip, {
            props: { canvases, current: canvases[0].id },
        });
        const pages = wrapper.findAll("button");
        expect(pages).toHaveLength(1);
        expect(pages[0].attributes("aria-current")).toBe("page");
        expect(pages[0].text()).toContain("f. 12r");
        await pages[0].trigger("click");
        expect(wrapper.emitted("select")?.[0]).toEqual([canvases[0].id]);
    });

    it("shows every page when none is analysed", () => {
        const canvases = documentPayload().canvases.map((canvas) => ({
            ...canvas,
            analysisCount: 0,
        }));
        const wrapper = mount(CanvasStrip, {
            props: { canvases, current: null },
        });
        expect(wrapper.findAll("button")).toHaveLength(2);
    });

    it("draws a thumbnail from the IIIF service and drops it once refused", async () => {
        const canvases = documentPayload().canvases.map((canvas) => ({
            ...canvas,
            image: {
                ...canvas.image,
                service: "https://iiif.example/image/p1",
            },
        }));
        const wrapper = mount(CanvasStrip, {
            props: { canvases, current: null },
        });
        const image = wrapper.find("img");
        expect(image.attributes("src")).toBe(
            "https://iiif.example/image/p1/full/,96/0/default.jpg",
        );
        await image.trigger("error");
        expect(wrapper.find("img").exists()).toBe(false);
    });
});
