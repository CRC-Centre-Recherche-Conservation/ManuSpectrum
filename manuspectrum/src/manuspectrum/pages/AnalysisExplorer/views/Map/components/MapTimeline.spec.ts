import { describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";

import MapTimeline from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/MapTimeline.vue";

import {
    label,
    mapEvent,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { MapEvent } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { TrackedMaterial } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/tracking.ts";

const LAPIS = "http://material.test/lapis";

function lapis() {
    return {
        id: LAPIS,
        name: label("Lapis lazuli"),
        reliability: null,
        characterization: uuid(300),
        colours: [],
        matches: true,
        componentColours: [],
    };
}

/** Ms A produced 1301–1325 with lapis, Ms B modified c. 1601–1625, Ms C altered undated. */
function events(): MapEvent[] {
    return [
        mapEvent({
            id: "production:a",
            document: { id: uuid(1), name: label("Ms A") },
            date: { start: 1301, end: 1325, approximate: false },
            materials: [lapis()],
        }),
        mapEvent({
            id: "modification:b",
            type: "modification",
            document: { id: uuid(2), name: label("Ms B") },
            date: { start: 1601, end: 1625, approximate: true },
        }),
        mapEvent({
            id: "alteration:c",
            type: "alteration",
            document: { id: uuid(3), name: label("Ms C") },
            date: { start: null, end: null, approximate: false },
        }),
    ];
}

function mountTimeline(
    props: {
        events?: MapEvent[];
        tracked?: TrackedMaterial[];
        brush?: [number, number] | null;
        approximate?: boolean;
    } = {},
) {
    return mount(MapTimeline, {
        props: {
            events: events(),
            tracked: [],
            brush: null,
            approximate: true,
            ...props,
        },
    });
}

function handles(wrapper: ReturnType<typeof mountTimeline>) {
    return wrapper.findAll("[role=slider]");
}

/** 560 px wide: 5.6 units (five 25-year bins and a 0.6 fold), 100 px each. */
function sizePlot(wrapper: ReturnType<typeof mountTimeline>): void {
    wrapper.find(".plot").element.getBoundingClientRect = () =>
        ({ left: 0, width: 560, right: 560 }) as DOMRect;
}

describe("MapTimeline", () => {
    it("stacks by event type without a followed material", () => {
        const wrapper = mountTimeline();
        expect(wrapper.find("svg[role=img]").attributes("aria-label")).toBe(
            "Events through time",
        );
        expect(wrapper.findAll(".part.type-production").length).toBe(1);
        expect(wrapper.findAll(".part.type-modification").length).toBe(1);
        expect(wrapper.find(".part.slot-1").exists()).toBe(false);
        expect(wrapper.find(".key").text()).toContain("Production");
    });

    it("stacks by followed material, the rest as other", () => {
        const wrapper = mountTimeline({ tracked: [{ uri: LAPIS, slot: 1 }] });
        expect(wrapper.findAll(".part.slot-1").length).toBe(1);
        expect(wrapper.findAll(".part.other").length).toBe(1);
        expect(wrapper.find(".part.type-production").exists()).toBe(false);
        expect(wrapper.find(".key").text()).toContain("Lapis lazuli");
    });

    it("carries the approximate-dates switch, ticked from its prop, and emits its change", async () => {
        const wrapper = mountTimeline();
        const box = wrapper.get(".head .approximate input[type='checkbox']");
        expect(wrapper.get(".head .approximate").text()).toBe(
            "Include approximate dates (“c.”)",
        );
        expect((box.element as HTMLInputElement).checked).toBe(true);
        await box.setValue(false);
        expect(wrapper.emitted("update:approximate")).toEqual([[false]]);
        const off = mountTimeline({ approximate: false });
        expect(
            (off.get(".approximate input").element as HTMLInputElement).checked,
        ).toBe(false);
    });

    it("draws an approximate date like any other, with no key entry of its own", () => {
        const wrapper = mountTimeline();
        const part = wrapper.find(".part.type-modification");
        expect(part.exists()).toBe(true);
        expect(part.attributes("class")).toBe("part type-modification");
        expect(wrapper.find(".key").text()).not.toContain("approximate");
    });

    it("folds the centuries without a dated event", () => {
        const wrapper = mountTimeline();
        const fold = wrapper.find("g.fold");
        expect(fold.find("text").text()).toBe("1401–1600");
        expect(fold.find("title").text()).toBe("No dated event");
    });

    it("opens a period from a bin button", async () => {
        const wrapper = mountTimeline();
        const bins = wrapper.findAll("button.bin");
        expect(bins[0].attributes("aria-label")).toBe("1301–1325: 1 event");
        await bins[0].trigger("click");
        expect(wrapper.emitted("open-period")).toEqual([
            [{ from: 1301, to: 1325 }],
        ]);
    });

    it("has no separate slider: the brush edges are the sliders", () => {
        const wrapper = mountTimeline();
        expect(wrapper.find(".range-slider").exists()).toBe(false);
        const edges = handles(wrapper);
        expect(edges).toHaveLength(2);
        expect(edges.every((edge) => edge.element.closest(".plot"))).toBe(true);
    });

    it("names the edges with their bounds, year and century", async () => {
        const wrapper = mountTimeline();
        const [low, high] = handles(wrapper);
        expect(low.attributes("aria-label")).toBe("Earliest year");
        expect(high.attributes("aria-label")).toBe("Latest year");
        expect(low.attributes("tabindex")).toBe("0");
        expect(high.attributes("tabindex")).toBe("0");
        expect(low.attributes("aria-valuemin")).toBe("1301");
        expect(low.attributes("aria-valuemax")).toBe("1625");
        expect(low.attributes("aria-valuenow")).toBe("1301");
        expect(low.attributes("aria-valuetext")).toBe("1301, 14th century");
        expect(high.attributes("aria-valuenow")).toBe("1625");
        expect(high.attributes("aria-valuetext")).toBe("1625, 17th century");

        await wrapper.setProps({ brush: [1326, 1400] });
        expect(low.attributes("aria-valuemax")).toBe("1400");
        expect(low.attributes("aria-valuenow")).toBe("1326");
        expect(high.attributes("aria-valuemin")).toBe("1326");
        expect(high.attributes("aria-valuemax")).toBe("1625");
        expect(high.attributes("aria-valuenow")).toBe("1400");
    });

    it("sits the edges at the domain ends without a brush, on the band with one", async () => {
        const wrapper = mountTimeline();
        const [low, high] = handles(wrapper);
        expect(low.attributes("style")).toContain("inset-inline-start: 0%");
        expect(high.attributes("style")).toContain("inset-inline-start: 100%");
        await wrapper.setProps({ brush: [1326, 1400] });
        const band = wrapper.find(".band").attributes("style");
        expect(band).toContain("inset-inline-start: 17.86%");
        expect(low.attributes("style")).toContain("inset-inline-start: 17.86%");
        expect(high.attributes("style")).toContain(
            "inset-inline-start: 71.43%",
        );
    });

    it("brushes by dragging an edge, once at the end of the drag", async () => {
        const wrapper = mountTimeline();
        sizePlot(wrapper);
        const [low, high] = handles(wrapper);
        await high.trigger("pointerdown", { clientX: 560, pointerId: 1 });
        await high.trigger("pointermove", { clientX: 399, pointerId: 1 });
        expect(wrapper.emitted("brush")).toBeUndefined();
        expect(high.attributes("aria-valuenow")).toBe("1400");
        expect(wrapper.find(".band").exists()).toBe(true);
        await high.trigger("pointerup", { clientX: 399, pointerId: 1 });
        expect(wrapper.emitted("brush")).toEqual([[[1301, 1400]]]);

        await wrapper.setProps({ brush: [1301, 1400] });
        await low.trigger("pointerdown", { clientX: 0, pointerId: 2 });
        await low.trigger("pointermove", { clientX: 101, pointerId: 2 });
        await low.trigger("pointerup", { clientX: 101, pointerId: 2 });
        expect(wrapper.emitted("brush")?.[1]).toEqual([[1326, 1400]]);
    });

    it("focuses an edge on a press and sets no brush when it does not move", async () => {
        const wrapper = mountTimeline();
        sizePlot(wrapper);
        const [low, high] = handles(wrapper);
        const focus = vi.spyOn(low.element as HTMLElement, "focus");
        await low.trigger("pointerdown", { clientX: 1, pointerId: 1 });
        expect(focus).toHaveBeenCalledWith({ preventScroll: true });
        await low.trigger("pointerup", { clientX: 2, pointerId: 1 });
        await high.trigger("pointerdown", { clientX: 559, pointerId: 2 });
        await high.trigger("pointermove", { clientX: 557, pointerId: 2 });
        await high.trigger("pointerup", { clientX: 557, pointerId: 2 });
        expect(wrapper.emitted("brush")).toBeUndefined();
    });

    it("never drags an edge past the other one nor out of the domain", async () => {
        const wrapper = mountTimeline({ brush: [1326, 1400] });
        sizePlot(wrapper);
        const [low, high] = handles(wrapper);
        await low.trigger("pointerdown", { clientX: 100, pointerId: 1 });
        await low.trigger("pointermove", { clientX: 520, pointerId: 1 });
        await low.trigger("pointerup", { clientX: 520, pointerId: 1 });
        await high.trigger("pointerdown", { clientX: 400, pointerId: 2 });
        await high.trigger("pointermove", { clientX: 900, pointerId: 2 });
        await high.trigger("pointerup", { clientX: 900, pointerId: 2 });
        await low.trigger("pointerdown", { clientX: 100, pointerId: 3 });
        await low.trigger("pointerup", { clientX: -300, pointerId: 3 });
        expect(wrapper.emitted("brush")).toEqual([
            [[1400, 1400]],
            [[1326, 1625]],
            [[1301, 1400]],
        ]);
    });

    it("moves an edge only while it is held, and stops on cancel", async () => {
        const wrapper = mountTimeline();
        sizePlot(wrapper);
        const [low] = handles(wrapper);
        await low.trigger("pointermove", { clientX: 101, pointerId: 1 });
        expect(low.attributes("aria-valuenow")).toBe("1301");
        await low.trigger("pointerup", { clientX: 101, pointerId: 1 });
        await low.trigger("pointerdown", { clientX: 0, pointerId: 2 });
        await low.trigger("pointermove", { clientX: 101, pointerId: 2 });
        expect(low.attributes("aria-valuenow")).toBe("1326");
        await low.trigger("pointercancel", { pointerId: 2 });
        await low.trigger("pointerup", { clientX: 101, pointerId: 2 });
        expect(wrapper.emitted("brush")).toBeUndefined();
        expect(low.attributes("aria-valuenow")).toBe("1301");
    });

    it("moves an edge by the slider's keys", async () => {
        const wrapper = mountTimeline({ brush: [1326, 1400] });
        const [low, high] = handles(wrapper);
        await low.trigger("keydown", { key: "ArrowRight" });
        await low.trigger("keydown", { key: "ArrowLeft" });
        await low.trigger("keydown", { key: "ArrowUp" });
        await low.trigger("keydown", { key: "ArrowDown" });
        await low.trigger("keydown", { key: "PageUp" });
        await low.trigger("keydown", { key: "PageDown" });
        await low.trigger("keydown", { key: "Home" });
        await high.trigger("keydown", { key: "End" });
        await high.trigger("keydown", { key: "PageUp" });
        await high.trigger("keydown", { key: "a" });
        expect(wrapper.emitted("brush")).toEqual([
            [[1327, 1400]],
            [[1325, 1400]],
            [[1327, 1400]],
            [[1325, 1400]],
            [[1351, 1400]],
            [[1301, 1400]],
            [[1301, 1400]],
            [[1326, 1625]],
            [[1326, 1425]],
        ]);
    });

    it("clamps the keys at the other edge and the domain", async () => {
        const wrapper = mountTimeline({ brush: [1390, 1400] });
        const [low, high] = handles(wrapper);
        await low.trigger("keydown", { key: "PageUp" });
        await low.trigger("keydown", { key: "End" });
        await high.trigger("keydown", { key: "Home" });
        const full = mountTimeline();
        const [first, last] = handles(full);
        await first.trigger("keydown", { key: "ArrowLeft" });
        await last.trigger("keydown", { key: "ArrowRight" });
        expect(wrapper.emitted("brush")).toEqual([
            [[1400, 1400]],
            [[1400, 1400]],
            [[1390, 1390]],
        ]);
        expect(full.emitted("brush")).toEqual([[[1301, 1625]], [[1301, 1625]]]);
    });

    it("clears the period", async () => {
        const wrapper = mountTimeline();
        expect(wrapper.find("button.clear").exists()).toBe(false);
        await wrapper.setProps({ brush: [1301, 1400] });
        expect(wrapper.find(".band").exists()).toBe(true);
        expect(wrapper.find("button.clear").text()).toBe("Whole period");
        expect(wrapper.find("button.clear").attributes("aria-label")).toBe(
            "Show the whole period",
        );
        await wrapper.find("button.clear").trigger("click");
        expect(wrapper.emitted("brush")).toEqual([[null]]);
    });

    it("explains the spread of imprecise dates and what the colours mean", async () => {
        const wrapper = mountTimeline();
        expect(wrapper.find(".explain").text()).toBe(
            "An imprecise date is spread over the bins it covers (“14th c.” = ¼ + ¼ + ¼ + ¼) · colours = event types",
        );
        await wrapper.setProps({ tracked: [{ uri: LAPIS, slot: 1 }] });
        expect(wrapper.find(".explain").text()).toContain(
            "colours = followed materials",
        );
    });

    it("fades the bins outside the brush", async () => {
        const wrapper = mountTimeline({ brush: [1301, 1325] });
        const columns = wrapper.findAll("g.column");
        expect(columns[0].classes()).not.toContain("out");
        expect(columns[columns.length - 1].classes()).toContain("out");
    });

    it("lists the brushed documents only, each opening its document", async () => {
        const wrapper = mountTimeline({ brush: [1301, 1400] });
        expect(wrapper.find(".documents .title").text()).toBe(
            "Documents of the period (1)",
        );
        const names = wrapper.findAll(".document-row .open");
        expect(names.map((name) => name.find(".name").text())).toEqual([
            "Ms A",
        ]);
        await names[0].trigger("click");
        expect(wrapper.emitted("open-document")).toEqual([[uuid(1)]]);

        await wrapper.setProps({ brush: null });
        expect(
            wrapper.findAll(".document-row .open .name").map((n) => n.text()),
        ).toEqual(["Ms A", "Ms B", "Ms C"]);
    });

    it("draws bars in the rows, with the followed pips", () => {
        const wrapper = mountTimeline({ tracked: [{ uri: LAPIS, slot: 2 }] });
        const rows = wrapper.findAll(".document-row");
        const bar = rows[0].find(".bar.type-production");
        expect(bar.attributes("style")).toContain("inset-inline-start: 0%");
        expect(bar.find(".focus-slot-dot").text()).toBe("2");
        expect(rows[1].find(".bar.type-modification").exists()).toBe(true);
        expect(rows[2].find(".bar").exists()).toBe(false);
    });

    it("says so when no event is dated", () => {
        const wrapper = mountTimeline({ events: events().slice(2) });
        expect(wrapper.find("svg.bars").exists()).toBe(false);
        expect(handles(wrapper)).toHaveLength(0);
        expect(wrapper.find(".empty").text()).toBe(
            "No dated event among the kept events.",
        );
    });
});
