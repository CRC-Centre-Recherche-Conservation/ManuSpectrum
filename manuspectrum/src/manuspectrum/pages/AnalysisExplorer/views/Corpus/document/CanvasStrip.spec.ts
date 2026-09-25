import { flushPromises, mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";

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

    describe("keyboard", () => {
        const canvases = ["f. 1r", "f. 1v", "f. 2r", "f. 2v"].map(
            (label, index) => ({
                id: `https://iiif.example/c${index + 1}`,
                label,
                image: { service: null, url: null, width: 1, height: 1 },
                analysisCount: index + 1,
                characterizationCount: 0,
            }),
        );

        function tabStops(wrapper: ReturnType<typeof mount>): string[] {
            return wrapper
                .findAll("button")
                .filter((button) => button.attributes("tabindex") === "0")
                .map((button) => button.find(".label").text());
        }

        it("is one tab stop, on the current page", () => {
            const wrapper = mount(CanvasStrip, {
                props: { canvases, current: canvases[2].id },
            });
            expect(tabStops(wrapper)).toEqual(["f. 2r"]);
        });

        it("moves between pages with the arrows, Home and End", async () => {
            const wrapper = mount(CanvasStrip, {
                props: { canvases, current: canvases[1].id },
                attachTo: document.body,
            });
            const list = wrapper.find("ul");
            await list.trigger("keydown", { key: "ArrowRight" });
            expect(document.activeElement?.textContent).toContain("f. 2r");
            expect(tabStops(wrapper)).toEqual(["f. 2r"]);
            await list.trigger("keydown", { key: "End" });
            expect(document.activeElement?.textContent).toContain("f. 2v");
            await list.trigger("keydown", { key: "Home" });
            expect(document.activeElement?.textContent).toContain("f. 1r");
            await list.trigger("keydown", { key: "ArrowLeft" });
            expect(document.activeElement?.textContent).toContain("f. 1r");
            expect(wrapper.emitted("select")).toBeUndefined();
            wrapper.unmount();
        });

        it("brings the current page into view when it changes", async () => {
            const wrapper = mount(CanvasStrip, {
                props: { canvases, current: canvases[0].id },
            });
            const scrollTo = vi.fn();
            (wrapper.find("ul").element as HTMLElement).scrollTo = scrollTo;
            await wrapper.setProps({ current: canvases[3].id });
            await flushPromises();
            expect(scrollTo).toHaveBeenCalled();
            expect(tabStops(wrapper)).toEqual(["f. 2v"]);
        });
    });
});
