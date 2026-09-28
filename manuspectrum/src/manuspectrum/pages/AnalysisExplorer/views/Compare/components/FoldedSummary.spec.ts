import { afterEach, describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import FoldedSummary from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/FoldedSummary.vue";

import type { VueWrapper } from "@vue/test-utils";
import type { FoldedSummary as Summary } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/folded-summary.ts";

let wrapper: VueWrapper | null = null;

afterEach(() => {
    wrapper?.unmount();
    wrapper = null;
});

function mountSummary(summary: Summary, title = "FTIR"): VueWrapper {
    wrapper = mount(FoldedSummary, { props: { summary, title } });
    return wrapper;
}

describe("FoldedSummary", () => {
    it("shows the slots of a folded XY window, its spectra counted, and offers to draw them", async () => {
        const view = mountSummary({
            kind: "xy",
            count: 4,
            slots: [2, 11, 12],
            names: ["FTIR"],
        });
        const chips = view.findAll(".slots li");
        expect(chips.map((chip) => chip.text())).toEqual(["A3", "A12", "A13"]);
        expect(chips[0].classes()).toContain("slot-3");
        expect(chips[1].classes()).toContain("slot-context");
        expect(view.find(".line").text()).toBe("4 FTIR spectra, not drawn");
        const draw = view.find("button.unfold");
        expect(draw.text()).toBe("Draw");
        expect(draw.attributes("aria-label")).toBe("Draw « FTIR »");
        await draw.trigger("click");
        expect(view.emitted("unfold")).toHaveLength(1);
    });

    it("counts the spectra without a technique name when none is known", () => {
        const view = mountSummary({
            kind: "xy",
            count: 1,
            slots: [0],
            names: [],
        });
        expect(view.find(".line").text()).toBe("1 spectrum, not drawn");
    });

    it("counts the maps with the layers they hold, and offers to show them", () => {
        const view = mountSummary(
            {
                kind: "maps",
                count: 2,
                slots: [0, 1],
                names: ["Pb", "Hg"],
            },
            "Element maps",
        );
        expect(view.find(".line").text()).toBe("2 maps · Pb, Hg");
        expect(view.find("button.unfold").text()).toBe("Show");
    });

    it("keeps the first slots and counts the others", () => {
        const view = mountSummary({
            kind: "xy",
            count: 12,
            slots: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
            names: [],
        });
        expect(view.findAll(".slots li").map((chip) => chip.text())).toEqual([
            "A1",
            "A2",
            "A3",
            "A4",
            "A5",
            "A6",
            "A7",
            "A8",
            "+4",
        ]);
    });

    it("shortens a long list of layers", () => {
        const view = mountSummary(
            {
                kind: "maps",
                count: 1,
                slots: [0],
                names: ["Pb", "Hg", "Fe", "Cu", "Ca", "K", "Zn", "Ti"],
            },
            "Element maps",
        );
        expect(view.find(".line").text()).toBe(
            "1 map · Pb, Hg, Fe, Cu, Ca, K…",
        );
    });
});
