import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { ref } from "vue";
import { createPinia, setActivePinia } from "pinia";

import CoverageMatrix from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/CoverageMatrix.vue";

import {
    FOLIO_REQUEST_KEY,
    LINKED_SELECTION_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { technique } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    SYNTHESIS,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    canvasNode,
    cellNode,
    elementNode,
    techniqueNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
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

let stop: (() => void) | null = null;

beforeEach(() => {
    setActivePinia(createPinia());
});

afterEach(() => {
    stop?.();
    stop = null;
    vi.useRealTimers();
});

function mountMatrix(disabled = false) {
    return mount(CoverageMatrix, {
        props: { rows: ROWS, techniques: [FORS, XRF], disabled },
    });
}

function mountLinked(): { view: VueWrapper; linked: LinkedSelection } {
    const started = startLinkedSelection();
    stop = started.stop;
    const view = mount(CoverageMatrix, {
        props: { rows: SYNTHESIS.coverage, techniques: SYNTHESIS.techniques },
        global: {
            provide: { [LINKED_SELECTION_KEY as symbol]: started.linked },
        },
    });
    return { view, linked: started.linked };
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

    it("shows each technique by its code, its full name read and shown on hover", () => {
        const view = mountMatrix();
        const header = view.find("thead .technique");
        expect(header.attributes("title")).toBe("FORS");
        expect(header.find(".name").classes()).toContain("visually-hidden");
    });

    it("shades each cell on the blue ramp by its count and says what the number counts", () => {
        const view = mountMatrix();
        expect(
            view
                .findAll("tbody .cell")
                .map((cell) => cell.attributes("data-heat")),
        ).toEqual(["2", "4", "2"]);
        const legend = view.find(".heat-legend");
        expect(legend.find(".caption").text()).toBe(
            "Analyses of the Selection on the folio with the technique",
        );
        expect(legend.findAll(".end").map((end) => end.text())).toEqual([
            "1",
            "2",
        ]);
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

    it("selects the cell, folio or technique clicked and presses its toggle", async () => {
        const view = mountMatrix();
        await view.findAll("tbody .cell")[0].trigger("click");
        await view.find("tbody .folio").trigger("click");
        await view.find("thead .technique").trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            cellNode("c1", "fors"),
            canvasNode("c1"),
            techniqueNode("fors"),
        ]);
        const pressed = view
            .findAll("button")
            .filter((button) => button.attributes("aria-pressed") === "true");
        expect(pressed.map((button) => button.text())).toEqual([
            "FORSFORS",
            "f. 1r",
            "1",
        ]);
    });

    it("shows the folio of a row header or a cell clicked in every folio image tool, and still toggles it", async () => {
        const show = vi.fn();
        const mountWith = (disabled: boolean) =>
            mount(CoverageMatrix, {
                props: { rows: ROWS, techniques: [FORS, XRF], disabled },
                global: {
                    provide: {
                        [FOLIO_REQUEST_KEY as symbol]: {
                            asked: ref(null),
                            show,
                        },
                    },
                },
            });
        const view = mountWith(false);
        await view.findAll("tbody .folio")[1].trigger("click");
        await view.findAll("tbody .cell")[0].trigger("click");
        expect(show.mock.calls).toEqual([
            ["c2", "f. 1v"],
            ["c1", "f. 1r"],
        ]);
        expect(useExplorerStore().compare.selection).toEqual([
            canvasNode("c2"),
            cellNode("c1", "fors"),
        ]);
        const stale = mountWith(true);
        await stale.find("tbody .folio").trigger("click");
        expect(show).toHaveBeenCalledTimes(2);
    });

    it("selects nothing while it is disabled", async () => {
        const view = mountMatrix(true);
        await view.find("tbody .cell").trigger("click");
        await view.find("tbody .folio").trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([]);
        expect(view.find("tbody .cell").attributes("aria-disabled")).toBe(
            "true",
        );
    });

    it("highlights the folios, techniques and cells linked to the selection and marks the others unlinked", async () => {
        const { view, linked } = mountLinked();
        expect(view.find("tbody tr").attributes("data-rel")).toBeUndefined();
        linked.toggle(elementNode("Cu"));
        await view.vm.$nextTick();
        expect(
            view.findAll("tbody tr").map((row) => row.attributes("data-rel")),
        ).toEqual(["direct", "none"]);
        expect(
            view.findAll("thead th[data-rel]").map((th) => th.text()),
        ).toEqual(["RamanRaman", "XRFXRF"]);
        expect(
            view.findAll("thead th").map((th) => th.attributes("data-rel")),
        ).toEqual([undefined, "none", "evidence"]);
        expect(
            view.findAll(".cell").map((cell) => cell.attributes("data-rel")),
        ).toEqual(["direct", "none"]);
    });

    it("previews what a folio under the mouse links", async () => {
        vi.useFakeTimers();
        const { view } = mountLinked();
        await view
            .findAll("tbody .folio")[1]
            .trigger("pointerenter", { pointerType: "mouse" });
        vi.runAllTimers();
        await view.vm.$nextTick();
        expect(
            view
                .findAll("tbody tr")
                .map((row) => row.attributes("data-preview")),
        ).toEqual([undefined, "self"]);
        expect(
            view
                .findAll(".cell")
                .map((cell) => cell.attributes("data-preview")),
        ).toEqual([undefined, "direct"]);
    });

    it("leaves out a technique no row shown counts", () => {
        const view = mount(CoverageMatrix, {
            props: { rows: [ROWS[1]], techniques: [FORS, XRF] },
        });
        expect(
            view.findAll('thead th[scope="col"]').map((th) => th.text()),
        ).toEqual(["Folio", "FORSFORS"]);
        expect(view.findAll("tbody td")).toHaveLength(1);
    });
});
