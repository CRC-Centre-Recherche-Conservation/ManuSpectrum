import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import MaterialsTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/MaterialsTable.vue";

import {
    characterization,
    label,
    uuid,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { MaterialRow } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

function row(slot: number, summary = characterization(slot)): MaterialRow {
    return { key: `ch:${summary.id}:-`, slot, characterization: summary };
}

function cells(wrapper: ReturnType<typeof mount>, index: number): string[] {
    return wrapper
        .findAll("tbody tr")
        [index].findAll("th, td")
        .map((cell) =>
            [...cell.element.querySelectorAll("span")]
                .map((span) => span.textContent?.trim())
                .filter(Boolean)
                .join(" "),
        );
}

describe("MaterialsTable", () => {
    it("heads its columns", () => {
        const wrapper = mount(MaterialsTable, { props: { rows: [row(0)] } });
        expect(wrapper.findAll("thead th").map((cell) => cell.text())).toEqual([
            "Selection",
            "Identified material",
            "Colours",
            "Materials",
            "Layers",
            "Elements",
            "Analyses cited as evidence",
        ]);
    });

    it("gives colours, materials with their certainty, layers, elements by level and the analyses cited", () => {
        const summary = characterization(1, {
            name: label("Blue of the mantle"),
            unpublished: true,
            colours: [
                valueRef("http://example.org/blue", "Blue"),
                valueRef("http://example.org/dark", "Dark"),
            ],
            materials: [
                {
                    value: valueRef("http://example.org/lapis", "Lapis lazuli"),
                    confidence: {
                        ...valueRef("http://example.org/certain", "Certain"),
                        rank: 1,
                    },
                    proportion: null,
                },
                {
                    value: valueRef("http://example.org/lead", "Lead white"),
                    confidence: null,
                    proportion: null,
                },
            ],
            layers: [valueRef("http://example.org/paint", "Paint layer")],
            elements: [
                {
                    level: {
                        ...valueRef("http://example.org/major", "Major"),
                        rank: 1,
                    },
                    values: [
                        valueRef("http://example.org/si", "Si"),
                        valueRef("http://example.org/al", "Al"),
                    ],
                },
                {
                    level: null,
                    values: [valueRef("http://example.org/pb", "Pb")],
                },
            ],
            evidence: [
                { id: uuid(101), name: label("MS1_XRF_01") },
                { id: uuid(102), name: label("MS1_FORS_02") },
            ],
        });
        const wrapper = mount(MaterialsTable, {
            props: { rows: [row(2, summary)] },
        });
        expect(cells(wrapper, 0)).toEqual([
            "A3",
            "Blue of the mantle Draft",
            "Blue, Dark",
            "Lapis lazuli Certain Lead white",
            "Paint layer",
            "Major: Si, Al Pb",
            "MS1_XRF_01 MS1_FORS_02",
        ]);
        expect(wrapper.find("tbody th").attributes("scope")).toBe("row");
    });

    it("marks what an identification does not state", () => {
        const wrapper = mount(MaterialsTable, {
            props: {
                rows: [
                    row(0, characterization(1, { colours: [], evidence: [] })),
                ],
            },
        });
        const [, , colours, , layers, elements, evidence] = cells(wrapper, 0);
        expect([colours, layers, elements, evidence]).toEqual([
            "—",
            "—",
            "—",
            "—",
        ]);
        expect(wrapper.findAll(".none")[0].attributes("aria-label")).toBe(
            "Not stated",
        );
    });
});
