import { describe, expect, it } from "vitest";
import { mount } from "@vue/test-utils";

import CoverageMatrix from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/CoverageMatrix.vue";

import { technique } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { SynthesisCoverage } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const XRF = technique("http://example.org/xrf", "XRF", 1, "xrf");
const FORS = technique("http://example.org/fors", "FORS", 2, "fors");
const ROWS: SynthesisCoverage[] = [
    {
        canvas: "c1",
        label: "f. 1r",
        document: "d",
        counts: { xrf: 2, fors: 1 },
    },
    { canvas: "c2", label: "f. 1v", document: "d", counts: { fors: 1 } },
];

function mountMatrix(pressed: [string, string] | null = null) {
    return mount(CoverageMatrix, {
        props: { rows: ROWS, techniques: [FORS, XRF], pressed },
    });
}

describe("CoverageMatrix", () => {
    it("lays canvases in rows and techniques in columns, each with a header", () => {
        const view = mountMatrix();
        expect(
            view.findAll('thead th[scope="col"]').map((th) => th.text()),
        ).toEqual(["Folio", "FORSFORS", "XRFXRF"]);
        expect(
            view.findAll('tbody th[scope="row"]').map((th) => th.text()),
        ).toEqual(["f. 1r", "f. 1v"]);
    });

    it("counts the analyses of a cell and says an empty cell holds none", () => {
        const view = mountMatrix();
        const cells = view.findAll("tbody tr")[1].findAll("td");
        expect(cells[0].find("button").text()).toBe("1");
        expect(cells[0].find("button").attributes("aria-label")).toBe(
            "f. 1v, FORS: 1 analysis",
        );
        expect(cells[1].find("button").exists()).toBe(false);
        expect(cells[1].text()).toContain("No published analysis");
    });

    it("presses the cell of the filter and emits the cell clicked", async () => {
        const view = mountMatrix(["c1", "xrf"]);
        const pressed = view
            .findAll("tbody button")
            .filter((button) => button.attributes("aria-pressed") === "true");
        expect(
            pressed.map((button) => button.attributes("aria-label")),
        ).toEqual(["f. 1r, XRF: 2 analyses"]);
        await view.findAll("tbody button")[0].trigger("click");
        expect(view.emitted("toggle")).toEqual([
            [{ canvas: "c1", technique: "fors" }],
        ]);
    });
});
