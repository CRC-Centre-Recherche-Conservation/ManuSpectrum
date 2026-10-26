import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";

import SmallMultiples from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/SmallMultiples.vue";

import {
    installDialog,
    pressEscape,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/dialog.ts";
import { label } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    fitAspect,
    project,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { Bounds } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
import type { MultiplesAxis } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-state.ts";
import type {
    MapSnapshot,
    MiniDot,
    MiniMap,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/multiples.ts";
import type { TrackedMaterial } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/tracking.ts";

const BOUNDS: Bounds = { west: -5, south: 42, east: 8, north: 51 };

function dot(id: string, overrides: Partial<MiniDot> = {}): MiniDot {
    return {
        id,
        lngLat: [2, 48],
        size: 1,
        attested: true,
        pale: false,
        slots: [],
        dashed: false,
        ...overrides,
    };
}

function materialMap(n: number, dots: MiniDot[] = [dot("p1")]): MiniMap {
    return {
        key: `http://material.test/m${n}`,
        title: label(`Material ${n}`),
        uri: `http://material.test/m${n}`,
        century: null,
        places: dots.filter((entry) => entry.attested).length,
        documents: n,
        components: n,
        dots,
    };
}

function mountMultiples(
    props: {
        maps?: MiniMap[];
        background?: MapSnapshot | null;
        page?: number;
        pages?: number;
        axis?: MultiplesAxis;
        tracked?: TrackedMaterial[];
        largeBackground?: MapSnapshot | null;
    } = {},
) {
    const wrapper = mount(SmallMultiples, {
        attachTo: document.body,
        props: {
            maps: [materialMap(1)],
            bounds: BOUNDS,
            background: null,
            page: 0,
            pages: 1,
            axis: "material" as MultiplesAxis,
            ...props,
        },
    });
    mounted.push(wrapper);
    return wrapper;
}

let removeDialog: () => void = () => undefined;
let mounted: VueWrapper[] = [];

beforeEach(() => {
    removeDialog = installDialog();
});

afterEach(() => {
    for (const wrapper of mounted) wrapper.unmount();
    mounted = [];
    removeDialog();
});

function enlargeButton(
    wrapper: ReturnType<typeof mountMultiples>,
    index = 0,
): HTMLButtonElement {
    return wrapper.findAll<HTMLButtonElement>("[data-action='enlarge']")[index]
        .element;
}

function dialogOf(wrapper: ReturnType<typeof mountMultiples>) {
    return wrapper.get<HTMLDialogElement>("dialog.series-map-dialog");
}

describe("SmallMultiples", () => {
    it("shows twelve maps per page", () => {
        const maps = Array.from({ length: 14 }, (_, n) => materialMap(n + 1));
        const first = mountMultiples({ maps, pages: 2 });
        expect(first.findAll("figure")).toHaveLength(12);
        const second = mountMultiples({ maps, page: 1, pages: 2 });
        expect(second.findAll("figure")).toHaveLength(2);
        expect(second.find("figcaption .title").text()).toBe("Material 13");
    });

    it("draws an analysed place without the material as a hollow dot", () => {
        const wrapper = mountMultiples({
            maps: [
                materialMap(1, [
                    dot("p1", { size: 2 }),
                    dot("p2", { attested: false }),
                ]),
            ],
        });
        const dots = wrapper.findAll("circle.dot");
        expect(dots[0].classes()).toContain("attested");
        expect(dots[0].attributes("r")).toBe("10");
        expect(dots[1].classes()).toContain("absent");
        expect(dots[1].attributes("r")).toBe("4");
    });

    it("draws a pale attestation hollow in the slot hue", () => {
        const wrapper = mountMultiples({
            maps: [materialMap(1, [dot("p1", { pale: true })])],
            tracked: [{ uri: "http://material.test/m1", slot: 2 }],
        });
        const pale = wrapper.find("circle.dot");
        expect(pale.classes()).toContain("pale");
        expect(pale.attributes("style")).toContain("--h: var(--focus-2)");
        expect(wrapper.find("figcaption .focus-slot-dot").text()).toBe("2");
    });

    it("draws one pip per followed slot by century", () => {
        const wrapper = mountMultiples({
            axis: "century",
            maps: [
                {
                    key: "century:13",
                    title: null,
                    uri: null,
                    century: 13,
                    places: 1,
                    documents: 3,
                    components: 4,
                    dots: [dot("p1", { slots: [1, 3] })],
                },
            ],
        });
        expect(wrapper.find("figcaption .title").text()).toBe("14th century");
        expect(wrapper.find("figcaption .counts").text()).toBe(
            "1 place · 3 documents",
        );
        expect(wrapper.findAll("circle.pip")).toHaveLength(2);
        expect(wrapper.find("circle.dot").exists()).toBe(false);
    });

    it("emits open with the map clicked", async () => {
        const map = materialMap(1);
        const wrapper = mountMultiples({ maps: [map] });
        const button = wrapper.find("figure button");
        expect(button.attributes("aria-label")).toBe(
            "Open Material 1: 1 place, 1 document, 1 Component",
        );
        await button.trigger("click");
        expect(wrapper.emitted("open")).toEqual([[map]]);
    });

    it("pages with the pager, the ends unavailable", async () => {
        expect(mountMultiples().find(".pager").exists()).toBe(false);
        const wrapper = mountMultiples({ page: 0, pages: 3 });
        expect(wrapper.find(".pager .page").text()).toBe("Page 1 / 3");
        const [previous, next] = wrapper.findAll(".pager button");
        expect(previous.attributes("aria-disabled")).toBe("true");
        await previous.trigger("click");
        await next.trigger("click");
        expect(wrapper.emitted("page")).toEqual([[1]]);
    });

    it("draws the land without a background, the snapshot with one", () => {
        const plain = mountMultiples();
        expect(plain.find("rect.land").exists()).toBe(true);
        expect(plain.find("image").exists()).toBe(false);
        const shot = mountMultiples({
            background: { url: "data:image/png;base64,x", bounds: BOUNDS },
        });
        expect(shot.find("image").attributes("href")).toBe(
            "data:image/png;base64,x",
        );
        expect(shot.find("rect.land").exists()).toBe(true);
    });

    it("lays the snapshot so that each dot sits on its place in the picture", () => {
        const shown = fitAspect(
            { west: -9, south: 40, east: 12, north: 53 },
            220,
            160,
        );
        const wrapper = mountMultiples({
            maps: [materialMap(1, [dot("p1", { lngLat: [-1.36, 48.68] })])],
            background: { url: "data:image/png;base64,x", bounds: shown },
        });
        const image = wrapper.find("image");
        expect(image.attributes("preserveAspectRatio")).toBe("none");
        const [x, y, width, height] = ["x", "y", "width", "height"].map(
            (name) => Number(image.attributes(name)),
        );
        const [inX, inY] = project([-1.36, 48.68], shown, width, height);
        const circle = wrapper.find("circle.dot");
        expect(
            Math.abs(Number(circle.attributes("cx")) - (x + inX)),
        ).toBeLessThan(0.1);
        expect(
            Math.abs(Number(circle.attributes("cy")) - (y + inY)),
        ).toBeLessThan(0.1);
    });

    it("draws an attributed place dashed", () => {
        const wrapper = mountMultiples({
            maps: [materialMap(1, [dot("p1", { dashed: true })])],
        });
        expect(wrapper.find("circle.dot").classes()).toContain("dashed");
    });

    it("explains the axis and says when there is nothing to draw", () => {
        const wrapper = mountMultiples({ maps: [] });
        expect(wrapper.find(".axis-note").text()).toContain(
            "One map per identified material",
        );
        expect(wrapper.find(".no-image").text()).toBe(
            "No identified material in the kept events.",
        );
    });

    it("gives every caption the same two lines, the name then the counts", () => {
        const wrapper = mountMultiples({
            maps: [materialMap(1, [dot("p1")]), materialMap(2, [dot("p2")])],
        });
        const captions = wrapper.findAll("figcaption");
        expect(captions).toHaveLength(2);
        for (const caption of captions) {
            expect(caption.element.children.length).toBe(3);
            expect(caption.element.children[0].classList.contains("name")).toBe(
                true,
            );
            expect(
                caption.element.children[1].classList.contains("counts"),
            ).toBe(true);
            expect(
                caption.element.children[2].classList.contains("enlarge"),
            ).toBe(true);
        }
    });

    it("names each « Enlarge » after its map", () => {
        const century: MiniMap = {
            ...materialMap(2),
            key: "century:13",
            title: null,
            uri: null,
            century: 13,
        };
        const wrapper = mountMultiples({ maps: [materialMap(1), century] });
        const labels = wrapper
            .findAll("[data-action='enlarge']")
            .map((button) =>
                document
                    .getElementById(button.attributes("aria-labelledby") ?? "")
                    ?.textContent?.trim(),
            );
        expect(labels).toEqual([
            "Enlarge the map of Material 1",
            "Enlarge the map of the 14th century",
        ]);
    });

    it("enlarges a map in a modal dialog that asks a snapshot at its own size, and gives the focus back on Escape", async () => {
        const maps = [materialMap(1), materialMap(2)];
        const wrapper = mountMultiples({ maps, pages: 1 });
        const dialog = dialogOf(wrapper);
        expect(dialog.element.open).toBe(false);
        const trigger = enlargeButton(wrapper, 1);
        trigger.focus();
        trigger.click();
        await flushPromises();
        const drawing = wrapper.get(".series-map-dialog .drawing").element;
        expect(dialog.element.open).toBe(true);
        expect(dialog.attributes("aria-label")).toBe("Material 2");
        expect(wrapper.emitted("enlarge-snapshot")).toEqual([
            [{ width: 960, height: 600 }],
        ]);
        expect(drawing.querySelector("svg")?.getAttribute("viewBox")).toBe(
            "0 0 960 600",
        );
        expect(document.documentElement.style.overflow).toBe("hidden");
        expect(document.activeElement?.getAttribute("data-action")).toBe(
            "close",
        );
        pressEscape(dialog.element);
        await flushPromises();
        expect(dialog.element.open).toBe(false);
        expect(document.activeElement).toBe(trigger);
        expect(document.documentElement.style.overflow).toBe("");
    });

    it("measures the drawing box of the dialog for the snapshot, and draws the large snapshot once it comes", async () => {
        const measured = vi
            .spyOn(HTMLElement.prototype, "getBoundingClientRect")
            .mockImplementation(function (this: HTMLElement) {
                return (
                    this.classList.contains("drawing")
                        ? { width: 1200.4, height: 700 }
                        : { width: 0, height: 0 }
                ) as DOMRect;
            });
        const wrapper = mountMultiples({
            background: { url: "data:image/png;base64,small", bounds: BOUNDS },
        });
        enlargeButton(wrapper).click();
        await flushPromises();
        measured.mockRestore();
        const drawing = wrapper.get(".series-map-dialog .drawing").element;
        expect(wrapper.emitted("enlarge-snapshot")).toEqual([
            [{ width: 1200, height: 700 }],
        ]);
        expect(drawing.querySelector("image")?.getAttribute("href")).toBe(
            "data:image/png;base64,small",
        );
        await wrapper.setProps({
            largeBackground: {
                url: "data:image/png;base64,large",
                bounds: BOUNDS,
            },
        });
        expect(drawing.querySelector("image")?.getAttribute("href")).toBe(
            "data:image/png;base64,large",
        );
        expect(drawing.querySelector("circle.dot")?.getAttribute("r")).toBe(
            "7",
        );
    });

    it("asks a new snapshot when the bounds change while the dialog is open, not for equal bounds", async () => {
        const wrapper = mountMultiples();
        enlargeButton(wrapper).click();
        await flushPromises();
        expect(wrapper.emitted("enlarge-snapshot")).toHaveLength(1);
        await wrapper.setProps({ bounds: { ...BOUNDS } });
        await flushPromises();
        expect(wrapper.emitted("enlarge-snapshot")).toHaveLength(1);
        await wrapper.setProps({ bounds: { ...BOUNDS, east: 12 } });
        await flushPromises();
        expect(wrapper.emitted("enlarge-snapshot")).toHaveLength(2);
    });

    it("closes when the series loses the enlarged map, the focus on a map left", async () => {
        const wrapper = mountMultiples({
            maps: [materialMap(1), materialMap(2)],
        });
        const trigger = enlargeButton(wrapper, 1);
        trigger.focus();
        trigger.click();
        await flushPromises();
        expect(dialogOf(wrapper).element.open).toBe(true);
        await wrapper.setProps({ maps: [materialMap(1)] });
        await flushPromises();
        expect(dialogOf(wrapper).element.open).toBe(false);
        expect(document.activeElement).toBe(wrapper.get(".mini .open").element);
    });

    it("steps through the series with the arrows and the buttons", async () => {
        const maps = [materialMap(1), materialMap(2), materialMap(3)];
        const wrapper = mountMultiples({ maps });
        enlargeButton(wrapper).click();
        await flushPromises();
        const dialog = dialogOf(wrapper);
        const title = () => wrapper.get(".series-map-dialog .title").text();
        expect(title()).toBe("Material 1");
        expect(
            dialog.get("[data-action='previous']").attributes("aria-disabled"),
        ).toBe("true");
        await dialog.trigger("keydown", { key: "ArrowRight" });
        expect(title()).toBe("Material 2");
        await dialog.get("[data-action='next']").trigger("click");
        expect(title()).toBe("Material 3");
        expect(wrapper.get(".series-map-dialog .position").text()).toBe(
            "Map 3 of 3",
        );
        await dialog.trigger("keydown", { key: "ArrowRight" });
        expect(title()).toBe("Material 3");
        await dialog.trigger("keydown", { key: "ArrowLeft" });
        expect(title()).toBe("Material 2");
        expect(wrapper.emitted("enlarge-snapshot")).toHaveLength(1);
    });

    it("closes with « Show on the map » and emits the map shown", async () => {
        const maps = [materialMap(1), materialMap(2)];
        const wrapper = mountMultiples({ maps });
        enlargeButton(wrapper, 1).click();
        await flushPromises();
        const show = wrapper.get(".series-map-dialog .show");
        expect(show.text()).toBe("Show on the map");
        await show.trigger("click");
        await flushPromises();
        expect(wrapper.emitted("show")).toEqual([[maps[1]]]);
        expect(dialogOf(wrapper).element.open).toBe(false);
    });
});
