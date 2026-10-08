import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import CenturyHistogram from "@/manuspectrum/pages/AnalysisExplorer/views/Corpus/components/CenturyHistogram.vue";

import { rangeFacet } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

function mountHistogram(selected: [number, number] | null = null) {
    return mount(CenturyHistogram, {
        props: {
            buckets: rangeFacet().buckets,
            min: 1030,
            max: 1465,
            selected,
        },
    });
}

describe("CenturyHistogram", () => {
    it("has one button per century, named with its century and its count", () => {
        const buttons = mountHistogram().findAll("button");
        expect(
            buttons.map((button) => button.attributes("aria-label")),
        ).toEqual([
            "11th century: 2 analyses",
            "12th century: 0 analyses",
            "13th century: 1 analysis",
            "14th century: 4 analyses",
            "15th century: 7 analyses",
        ]);
        expect(buttons.map((button) => button.attributes("title"))).toEqual(
            buttons.map((button) => button.attributes("aria-label")),
        );
    });

    it("draws each bar in proportion to the highest count", () => {
        const bars = mountHistogram().findAll(".bar");
        expect(
            bars.map(
                (bar) =>
                    bar.attributes("style")?.match(/--bar: ([\d.]+)%/)?.[1],
            ),
        ).toEqual(["28.5714", "0", "14.2857", "57.1429", "100"]);
    });

    it("labels the centuries with their ordinal", () => {
        const labels = mountHistogram()
            .findAll(".label")
            .map((label) => label.text());
        expect(labels).toEqual(["11th", "12th", "13th", "14th", "15th"]);
    });

    it("presses a century lying entirely within the period, the bounds counting as its ends", () => {
        const pressed = (selected: [number, number] | null) =>
            mountHistogram(selected)
                .findAll("button")
                .map((button) => button.attributes("aria-pressed"));
        expect(pressed(null)).toEqual(Array(5).fill("false"));
        expect(pressed([1201, 1400])).toEqual([
            "false",
            "false",
            "true",
            "true",
            "false",
        ]);
        expect(pressed([1030, 1465])).toEqual(Array(5).fill("true"));
        expect(pressed([1302, 1400])).toEqual(Array(5).fill("false"));
    });

    it("emits the century picked", async () => {
        const wrapper = mountHistogram();
        await wrapper.findAll("button")[3].trigger("click");
        expect(wrapper.emitted("select")).toEqual([[1301, 1400]]);
    });
});
