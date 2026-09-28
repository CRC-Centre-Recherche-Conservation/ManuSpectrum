import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import ColourMaterialTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ColourMaterialTable.vue";

import { valueRef } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { SynthesisPair } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const BLUE = valueRef("http://example.org/blue", "Blue");
const AZURITE = valueRef("http://example.org/azurite", "Azurite");
const CHALK = valueRef("http://example.org/chalk", "Chalk");
const PAIRS: SynthesisPair[] = [
    {
        colour: BLUE,
        material: AZURITE,
        elements: [
            { ...valueRef("http://example.org/cu", "Copper"), symbol: "Cu" },
            { ...valueRef("http://example.org/pb", "Lead"), symbol: null },
        ],
        canvases: ["c1", "c3"],
        confidenceBest: {
            ...valueRef("http://example.org/reliable", "Reliable"),
            rank: 1,
        },
        count: 2,
        techniques: [],
    },
    {
        colour: null,
        material: CHALK,
        elements: [],
        canvases: [],
        confidenceBest: null,
        count: 1,
        techniques: [],
    },
];

function mountTable(pressed: [string | null, string] | null = null) {
    return mount(ColourMaterialTable, {
        props: {
            pairs: PAIRS,
            canvasLabels: new Map([["c1", "f. 1r"]]),
            pressed,
        },
    });
}

describe("ColourMaterialTable", () => {
    it("shows each pair with its elements, folios, best certainty and count", () => {
        const view = mountTable();
        const cells = view.findAll("tbody tr")[0].findAll("th, td");
        expect(cells.map((cell) => cell.text())).toEqual([
            "Blue",
            "Azurite",
            "Cu, Lead",
            "f. 1r, 1 other folio",
            "Reliable",
            "2",
        ]);
        expect(view.findAll("tbody tr")[1].findAll("th, td")[0].text()).toBe(
            "No colour stated",
        );
    });

    it("presses the row of the filter and emits the pair of a row clicked", async () => {
        const view = mountTable([BLUE.id, AZURITE.id]);
        const buttons = view.findAll("tbody button");
        expect(
            buttons.map((button) => button.attributes("aria-pressed")),
        ).toEqual(["true", "false"]);
        await view.findAll("tbody tr")[1].find("td").trigger("click");
        await buttons[0].trigger("click");
        expect(view.emitted("toggle")).toEqual([
            [{ colour: null, material: CHALK.id }],
            [{ colour: BLUE.id, material: AZURITE.id }],
        ]);
    });

    it("names each row's toggle by its colour and material", () => {
        const view = mountTable();
        expect(
            view
                .findAll("tbody button")
                .map((button) => button.attributes("aria-label")),
        ).toEqual(["Blue, Azurite", "No colour, Chalk"]);
    });
});
