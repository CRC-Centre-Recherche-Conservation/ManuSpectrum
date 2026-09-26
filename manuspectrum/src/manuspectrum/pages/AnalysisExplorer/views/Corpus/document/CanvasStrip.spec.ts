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

    it("draws no thumbnail from a service outside http(s)", () => {
        const canvases = documentPayload().canvases.map((canvas) => ({
            ...canvas,
            image: { ...canvas.image, service: "javascript:alert(1)//" },
        }));
        const wrapper = mount(CanvasStrip, {
            props: { canvases, current: null },
        });
        expect(wrapper.find("img").exists()).toBe(false);
    });

    describe("with filters", () => {
        const canvases = ["f. 1r", "f. 1v", "f. 2r", "f. 2v"].map(
            (label, index) => ({
                id: `https://iiif.example/c${index + 1}`,
                label,
                image: { service: null, url: null, width: 1, height: 1 },
                analysisCount: 2,
                characterizationCount: 0,
            }),
        );
        const counts = new Map([
            [
                canvases[0].id,
                { total: 2, matching: 0, materials: 1, samples: 0 },
            ],
            [
                canvases[1].id,
                { total: 2, matching: 2, materials: 0, samples: 3 },
            ],
            [
                canvases[2].id,
                { total: 2, matching: 0, materials: 0, samples: 0 },
            ],
            [
                canvases[3].id,
                { total: 2, matching: 1, materials: 0, samples: 0 },
            ],
        ]);

        function mountFiltered(current = canvases[0].id) {
            return mount(CanvasStrip, {
                props: { canvases, current, counts, filtered: true },
            });
        }

        it("writes per page the analyses the filters keep out of all, and marks the pages with some", () => {
            const pages = mountFiltered().findAll("button.page");
            expect(pages[1].find(".count [aria-hidden]").text()).toBe("2/2");
            expect(pages[1].find(".count").text()).toContain(
                "2 of 2 analyses in the filters",
            );
            expect(pages[0].find(".count [aria-hidden]").text()).toBe("0/2");
            expect(pages[1].classes()).toContain("has-match");
            expect(pages[0].classes()).not.toContain("has-match");
        });

        it("counts the identified materials and samples of a page", () => {
            const pages = mountFiltered().findAll("button.page");
            expect(pages[0].find(".materials").text()).toContain(
                "1 identified material",
            );
            expect(pages[1].find(".samples").text()).toContain("3 samples");
            expect(pages[2].find(".materials").exists()).toBe(false);
        });

        it("keeps only the pages with results on demand", async () => {
            const wrapper = mountFiltered();
            await wrapper.find("input.only-results").setValue(true);
            expect(
                wrapper.findAll("button.page").map((page) => page.text()),
            ).toEqual([
                expect.stringContaining("f. 1v"),
                expect.stringContaining("f. 2v"),
            ]);
        });

        it("goes to the previous or next page with results", async () => {
            const wrapper = mountFiltered(canvases[2].id);
            await wrapper.find("button.next-result").trigger("click");
            await wrapper.find("button.previous-result").trigger("click");
            expect(wrapper.emitted("select")).toEqual([
                [canvases[3].id],
                [canvases[1].id],
            ]);
            const last = mountFiltered(canvases[3].id);
            expect(
                last.find("button.next-result").attributes("disabled"),
            ).toBeDefined();
        });
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
