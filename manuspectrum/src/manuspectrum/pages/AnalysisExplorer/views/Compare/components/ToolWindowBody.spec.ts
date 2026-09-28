import { beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import ToolWindowBody from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ToolWindowBody.vue";

import { ANNOUNCE_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    technique,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { Pinia } from "pinia";
import type { SynthesisResponse } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const BLUE = valueRef("http://example.org/blue", "Blue");
const AZURITE = valueRef("http://example.org/azurite", "Azurite");
const CHALK = valueRef("http://example.org/chalk", "Chalk");
const SYNTHESIS: SynthesisResponse = {
    coverage: [
        { canvas: "c1", label: "f. 1r", document: "d", counts: { xrf: 2 } },
        { canvas: "c2", label: "f. 1v", document: "d", counts: { xrf: 1 } },
    ],
    canvases: [
        { canvas: "c1", label: "f. 1r", document: "d" },
        { canvas: "c2", label: "f. 1v", document: "d" },
        { canvas: "c3", label: "f. 2r", document: "d" },
    ],
    techniques: [technique("http://example.org/xrf", "XRF", 1, "xrf")],
    pairs: [
        {
            colour: BLUE,
            material: AZURITE,
            elements: [
                {
                    ...valueRef("http://example.org/cu", "Copper"),
                    symbol: "Cu",
                },
            ],
            canvases: ["c1", "c3"],
            confidenceBest: null,
            count: 2,
            techniques: ["xrf"],
        },
        {
            colour: null,
            material: CHALK,
            elements: [
                {
                    ...valueRef("http://example.org/ca", "Calcium"),
                    symbol: "Ca",
                },
            ],
            canvases: ["c2"],
            confidenceBest: null,
            count: 1,
            techniques: ["xrf"],
        },
    ],
    elements: [
        { symbol: "Cu", level: null, count: 2 },
        { symbol: "Ca", level: null, count: 1 },
    ],
    unpublishedCount: 0,
};

let pinia: Pinia;
let announce: ReturnType<typeof vi.fn>;

beforeEach(() => {
    pinia = createPinia();
    setActivePinia(pinia);
    announce = vi.fn();
});

type BodyProps = InstanceType<typeof ToolWindowBody>["$props"];

function mountBody(props: Partial<BodyProps> & Pick<BodyProps, "kind">) {
    return mount(ToolWindowBody, {
        props: { status: "ready", synthesis: SYNTHESIS, ...props },
        global: {
            plugins: [pinia],
            provide: { [ANNOUNCE_KEY as symbol]: announce },
            stubs: { FolioTool: true },
        },
    });
}

describe("ToolWindowBody", () => {
    it("filters the other tools by the element clicked, and says so", async () => {
        const periodic = mountBody({ kind: "periodic" });
        const table = mountBody({ kind: "colour-material" });
        const matrix = mountBody({ kind: "coverage" });
        await periodic
            .find('.grid button[aria-label="Cu, 2"]')
            .trigger("click");
        expect(useExplorerStore().compare.toolFilters.element).toBe("Cu");
        expect(announce).toHaveBeenLastCalledWith("Tools filtered by Cu");
        expect(
            periodic
                .find('.grid button[aria-label="Cu, 2"]')
                .attributes("aria-pressed"),
        ).toBe("true");
        expect(periodic.find(".chip").exists()).toBe(false);
        expect(table.find(".chip").text()).toBe("Filtered by Cu×");
        expect(table.findAll("tbody tr")).toHaveLength(1);
        expect(
            matrix.findAll("tbody tr").map((row) => row.find("th").text()),
        ).toEqual(["f. 1r"]);
    });

    it("clears a filter from its chip, or by clicking the pressed control again", async () => {
        const table = mountBody({ kind: "colour-material" });
        const periodic = mountBody({ kind: "periodic" });
        await table.findAll("tbody tr")[1].trigger("click");
        expect(useExplorerStore().compare.toolFilters.pair).toEqual([
            null,
            CHALK.id,
        ]);
        const chip = periodic.find(".chip");
        expect(chip.text()).toBe("Filtered by Chalk×");
        expect(chip.attributes("aria-label")).toBe(
            "Filtered by Chalk. Remove this filter",
        );
        expect(periodic.findAll(".grid button")).toHaveLength(1);
        await chip.trigger("click");
        expect(useExplorerStore().compare.toolFilters.pair).toBeNull();
        expect(announce).toHaveBeenLastCalledWith("Filter removed: Chalk");
        await table.findAll("tbody tr")[0].trigger("click");
        await table.findAll("tbody tr")[0].trigger("click");
        expect(useExplorerStore().compare.toolFilters.pair).toBeNull();
    });

    it("filters by a coverage cell, named by its folio and technique", async () => {
        const matrix = mountBody({ kind: "coverage" });
        const periodic = mountBody({ kind: "periodic" });
        await matrix.findAll("tbody button")[1].trigger("click");
        expect(useExplorerStore().compare.toolFilters.cell).toEqual([
            "c2",
            "xrf",
        ]);
        expect(periodic.find(".chip").text()).toBe("Filtered by f. 1v · XRF×");
        expect(
            periodic
                .findAll(".grid button")
                .map((button) => button.attributes("aria-label")),
        ).toEqual(["Ca, 1"]);
    });

    it("says when nothing matches the filters", async () => {
        useExplorerStore().setToolFilter("element", "Cu");
        useExplorerStore().setToolFilter("cell", ["c2", "xrf"]);
        const table = mountBody({ kind: "colour-material" });
        expect(table.find(".empty").text()).toBe(
            "Nothing matches the filters.",
        );
        expect(table.findAll(".chip")).toHaveLength(2);
    });

    it("says when the Selection has nothing for the tool", () => {
        const periodic = mountBody({
            kind: "periodic",
            synthesis: { ...SYNTHESIS, elements: [] },
        });
        expect(periodic.find(".empty").text()).toBe(
            "Nothing to show for this Selection.",
        );
    });

    it("says the synthesis is being read, or offers a retry when it failed", async () => {
        const loading = mountBody({
            kind: "coverage",
            status: "loading",
            synthesis: null,
        });
        expect(loading.find(".loading").text()).toBe("Reading the Selection…");
        const failed = mountBody({
            kind: "coverage",
            status: "error",
            synthesis: null,
        });
        await failed.find(".unavailable-state .retry").trigger("click");
        expect(failed.emitted("retry")).toHaveLength(1);
        const gone = mountBody({
            kind: "coverage",
            status: "unavailable",
            synthesis: null,
        });
        expect(gone.find(".empty").text()).toBe(
            "Nothing in the Selection is available any more.",
        );
    });

    it("names the folios of a pair from every canvas the Selection is placed on", () => {
        const table = mountBody({ kind: "colour-material" });
        expect(table.findAll("tbody tr")[0].findAll("td")[2].text()).toBe(
            "f. 1r, f. 2r",
        );
    });

    it("gives the folio image every placed canvas, with or without coverage", () => {
        const folio = mountBody({
            kind: "folio",
            synthesis: { ...SYNTHESIS, coverage: [] },
        });
        expect(folio.find(".empty").exists()).toBe(false);
        expect(
            folio.findComponent({ name: "FolioTool" }).props("canvases"),
        ).toEqual(SYNTHESIS.canvases);
    });

    it("shows only the failure and Retry when the synthesis failed, whatever it showed before", () => {
        const failed = mountBody({ kind: "periodic", status: "error" });
        expect(failed.find(".unavailable-state").exists()).toBe(true);
        expect(failed.find(".periodic-table").exists()).toBe(false);
        expect(failed.find(".chips").exists()).toBe(false);
    });

    it("says the synthesis is being read over the previous one, and takes no filter from it", async () => {
        const periodic = mountBody({ kind: "periodic", status: "loading" });
        expect(periodic.find(".loading").text()).toBe("Reading the Selection…");
        expect(periodic.find(".tool-window-body").attributes("aria-busy")).toBe(
            "true",
        );
        await periodic
            .find('.grid button[aria-label="Cu, 2"]')
            .trigger("click");
        expect(useExplorerStore().compare.toolFilters.element).toBeNull();
        expect(announce).not.toHaveBeenCalled();
    });
});
