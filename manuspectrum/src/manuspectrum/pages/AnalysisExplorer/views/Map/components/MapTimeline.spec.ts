import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import RangeSlider from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/RangeSlider.vue";
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
    } = {},
) {
    return mount(MapTimeline, {
        props: {
            events: events(),
            tracked: [],
            brush: null,
            ...props,
        },
    });
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

    it("draws approximate parts lighter", () => {
        const wrapper = mountTimeline();
        const approx = wrapper.findAll(".part.approx");
        expect(approx).toHaveLength(1);
        expect(approx[0].classes()).toContain("type-modification");
        expect(wrapper.find(".key").text()).toContain(
            "lighter = approximate date",
        );
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

    it("emits the brush from the slider and clears it", async () => {
        const wrapper = mountTimeline();
        expect(wrapper.find("button.clear").exists()).toBe(false);
        const slider = wrapper.findComponent(RangeSlider);
        expect(slider.props("min")).toBe(1301);
        expect(slider.props("max")).toBe(1625);
        slider.vm.$emit("change", [1301, 1400]);
        expect(wrapper.emitted("brush")).toEqual([[[1301, 1400]]]);

        await wrapper.setProps({ brush: [1301, 1400] });
        expect(slider.props("value")).toEqual([1301, 1400]);
        expect(wrapper.find(".band").exists()).toBe(true);
        await wrapper.find("button.clear").trigger("click");
        expect(wrapper.emitted("brush")?.[1]).toEqual([null]);
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
        expect(rows[1].find(".bar.approx").exists()).toBe(true);
        expect(rows[2].find(".bar").exists()).toBe(false);
    });

    it("says so when no event is dated", () => {
        const wrapper = mountTimeline({ events: events().slice(2) });
        expect(wrapper.find("svg.bars").exists()).toBe(false);
        expect(wrapper.findComponent(RangeSlider).exists()).toBe(false);
        expect(wrapper.find(".empty").text()).toBe(
            "No dated event among the kept events.",
        );
    });
});
