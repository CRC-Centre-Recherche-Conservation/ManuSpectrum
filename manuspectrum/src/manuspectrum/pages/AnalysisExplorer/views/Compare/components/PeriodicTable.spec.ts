import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import PeriodicTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/PeriodicTable.vue";

import { valueRef } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

const ELEMENTS = [
    {
        symbol: "Cu",
        level: { ...valueRef("http://example.org/major", "Major"), rank: 0 },
        count: 5,
        materials: [],
    },
    { symbol: "Pb", level: null, count: 2, materials: [] },
    { symbol: "Xy", level: null, count: 1, materials: [] },
];

function mountTable(pressed: string | null = null) {
    return mount(PeriodicTable, { props: { elements: ELEMENTS, pressed } });
}

describe("PeriodicTable", () => {
    it("lays the 118 elements on the grid, the ones found as buttons with their count", () => {
        const view = mountTable();
        const grid = view.find(".grid");
        expect(grid.findAll(".cell")).toHaveLength(118);
        const found = grid.findAll("button");
        expect(found.map((button) => button.attributes("aria-label"))).toEqual([
            "Cu, 5",
            "Pb, 2",
        ]);
        expect(found[0].text()).toBe("Cu5");
        expect(found[0].classes()).toEqual(
            expect.arrayContaining(["row-4", "column-11"]),
        );
    });

    it("lists an element outside the table after the grid", () => {
        const view = mountTable();
        expect(
            view
                .findAll(".others button")
                .map((button) => button.attributes("aria-label")),
        ).toEqual(["Xy, 1"]);
    });

    it("lists the elements found for narrow screens, most frequent first", () => {
        const view = mountTable();
        expect(
            view.findAll(".list button").map((button) => button.text()),
        ).toEqual(["Cu5Major", "Pb2", "Xy1"]);
    });

    it("presses the element of the filter and emits the element clicked", async () => {
        const view = mountTable("Pb");
        expect(
            view
                .findAll(".grid button")
                .map((button) => button.attributes("aria-pressed")),
        ).toEqual(["false", "true"]);
        await view.find(".list button").trigger("click");
        expect(view.emitted("toggle")).toEqual([[{ symbol: "Cu" }]]);
    });
});
