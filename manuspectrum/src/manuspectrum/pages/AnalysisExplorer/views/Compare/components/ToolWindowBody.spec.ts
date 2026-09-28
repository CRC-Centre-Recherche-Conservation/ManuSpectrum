import { beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import ToolWindowBody from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ToolWindowBody.vue";

import {
    ANNOUNCE_KEY,
    LINKED_SELECTION_KEY,
} from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    technique,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { startLinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    cellNode,
    elementNode,
    pairNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

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
        {
            canvas: "c1",
            label: "f. 1r",
            document: "d",
            selected: true,
            analyses: [],
            materials: [],
        },
        {
            canvas: "c2",
            label: "f. 1v",
            document: "d",
            selected: true,
            analyses: [],
            materials: [],
        },
        {
            canvas: "c3",
            label: "f. 2r",
            document: "d",
            selected: false,
            analyses: [],
            materials: [],
        },
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
            materials: [],
            confidenceBest: null,
            count: 2,
            cells: [
                ["c1", "xrf"],
                ["c3", "xrf"],
            ],
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
            materials: [],
            confidenceBest: null,
            count: 1,
            cells: [["c2", "xrf"]],
        },
    ],
    elements: [
        { symbol: "Cu", level: null, count: 2, materials: [] },
        { symbol: "Ca", level: null, count: 1, materials: [] },
    ],
    materials: [],
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
    it("selects the element clicked, pressed, without filtering the other tools", async () => {
        const periodic = mountBody({ kind: "periodic" });
        const table = mountBody({ kind: "colour-material" });
        const matrix = mountBody({ kind: "coverage" });
        const cu = () => periodic.find('.grid button[aria-label="Cu, 2"]');
        await cu().trigger("click");
        expect(useExplorerStore().compare.selection).toEqual(["el:Cu"]);
        expect(cu().attributes("aria-pressed")).toBe("true");
        expect(periodic.find(".chip").exists()).toBe(false);
        expect(table.findAll("tbody tr")).toHaveLength(2);
        expect(matrix.findAll("tbody tr")).toHaveLength(2);
        await cu().trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([]);
        expect(cu().attributes("aria-pressed")).toBe("false");
    });

    it("adds each pair and cell clicked to the selection, several at once", async () => {
        const table = mountBody({ kind: "colour-material" });
        const matrix = mountBody({ kind: "coverage" });
        await table.findAll("tbody tr")[1].trigger("click");
        await table.findAll("tbody tr")[0].trigger("click");
        await matrix.findAll("tbody .cell")[1].trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            pairNode(null, CHALK.id),
            pairNode(BLUE.id, AZURITE.id),
            cellNode("c2", "xrf"),
        ]);
        expect(
            table
                .findAll("tbody button")
                .map((button) => button.attributes("aria-pressed")),
        ).toEqual(["true", "true"]);
        expect(
            matrix
                .findAll("tbody .cell")
                .map((button) => button.attributes("aria-pressed")),
        ).toEqual(["false", "true"]);
    });

    it("toggles through the linked selection of the view when there is one", async () => {
        const { linked, stop } = startLinkedSelection();
        const toggle = vi.spyOn(linked, "toggle");
        const periodic = mount(ToolWindowBody, {
            props: { kind: "periodic", status: "ready", synthesis: SYNTHESIS },
            global: {
                plugins: [pinia],
                provide: { [LINKED_SELECTION_KEY as symbol]: linked },
            },
        });
        await periodic
            .find('.grid button[aria-label="Ca, 1"]')
            .trigger("click");
        expect(toggle).toHaveBeenCalledWith("el:Ca");
        stop();
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

    it("gives the folio image the canvases holding a Selection item, with or without coverage", () => {
        const folio = mountBody({
            kind: "folio",
            synthesis: { ...SYNTHESIS, coverage: [] },
        });
        expect(folio.find(".empty").exists()).toBe(false);
        expect(
            folio.findComponent({ name: "FolioTool" }).props("canvases"),
        ).toEqual(SYNTHESIS.canvases.slice(0, 2));
    });

    it("has no folio image when only citing materials are placed", () => {
        const folio = mountBody({
            kind: "folio",
            synthesis: {
                ...SYNTHESIS,
                canvases: [SYNTHESIS.canvases[2]],
            },
        });
        expect(folio.find(".empty").text()).toBe(
            "Nothing to show for this Selection.",
        );
    });

    it("shows only the failure and Retry when the synthesis failed, whatever it showed before", () => {
        const failed = mountBody({ kind: "periodic", status: "error" });
        expect(failed.find(".unavailable-state").exists()).toBe(true);
        expect(failed.find(".periodic-table").exists()).toBe(false);
    });

    it("says the synthesis is being read over the previous one, and selects nothing from it", async () => {
        useExplorerStore().toggleSelection(elementNode("Ca"));
        const periodic = mountBody({ kind: "periodic", status: "loading" });
        expect(periodic.find(".loading").text()).toBe("Reading the Selection…");
        expect(periodic.find(".view .loading").exists()).toBe(false);
        expect(
            periodic.find(".tool-window-body").attributes("aria-busy"),
        ).toBeUndefined();
        expect(periodic.find(".view").attributes("aria-busy")).toBe("true");
        const toggles = periodic.findAll(".view button");
        expect(toggles.length).toBeGreaterThan(1);
        expect(
            toggles.every(
                (button) => button.attributes("aria-disabled") === "true",
            ),
        ).toBe(true);
        await periodic
            .find('.grid button[aria-label="Cu, 2"]')
            .trigger("click");
        expect(useExplorerStore().compare.selection).toEqual(["el:Ca"]);
        expect(announce).not.toHaveBeenCalled();
    });

    it("marks the stale matrix and table toggles disabled while the synthesis is read", () => {
        for (const kind of ["coverage", "colour-material"] as const) {
            const body = mountBody({ kind, status: "loading" });
            const toggles = body.findAll(".view tbody button");
            expect(toggles.length).toBeGreaterThan(0);
            expect(
                toggles.every(
                    (button) => button.attributes("aria-disabled") === "true",
                ),
            ).toBe(true);
        }
        const ready = mountBody({ kind: "coverage" });
        expect(
            ready.find(".view tbody button").attributes("aria-disabled"),
        ).toBeUndefined();
    });
});
