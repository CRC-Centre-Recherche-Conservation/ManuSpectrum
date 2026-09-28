import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import ColourMaterialTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/ColourMaterialTable.vue";

import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { valueRef } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    SYNTHESIS,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    elementNode,
    pairNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
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
        materials: [],
        confidenceBest: {
            ...valueRef("http://example.org/reliable", "Reliable"),
            rank: 1,
        },
        count: 2,
        cells: [],
    },
    {
        colour: null,
        material: CHALK,
        elements: [],
        canvases: [],
        materials: [],
        confidenceBest: null,
        count: 1,
        cells: [],
    },
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

function mountTable(disabled = false) {
    return mount(ColourMaterialTable, {
        props: {
            pairs: PAIRS,
            canvasLabels: new Map([["c1", "f. 1r"]]),
            disabled,
        },
    });
}

function mountLinked(): { view: VueWrapper; linked: LinkedSelection } {
    const started = startLinkedSelection();
    stop = started.stop;
    const view = mount(ColourMaterialTable, {
        props: { pairs: SYNTHESIS.pairs, canvasLabels: new Map() },
        global: {
            provide: { [LINKED_SELECTION_KEY as symbol]: started.linked },
        },
    });
    return { view, linked: started.linked };
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

    it("selects the pair of a row clicked and presses its toggle", async () => {
        const view = mountTable();
        await view.findAll("tbody tr")[1].find("td").trigger("click");
        await view.findAll("tbody button")[0].trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            pairNode(null, CHALK.id),
            pairNode(BLUE.id, AZURITE.id),
        ]);
        expect(
            view
                .findAll("tbody button")
                .map((button) => button.attributes("aria-pressed")),
        ).toEqual(["true", "true"]);
        expect(
            view.findAll("tbody tr").map((row) => row.attributes("data-rel")),
        ).toEqual([undefined, undefined]);
    });

    it("selects nothing while it is disabled", async () => {
        const view = mountTable(true);
        await view.findAll("tbody button")[0].trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([]);
    });

    it("highlights the pairs linked to the selection and marks the others unlinked", async () => {
        const { view, linked } = mountLinked();
        linked.toggle(elementNode("Cu"));
        await view.vm.$nextTick();
        expect(
            view.findAll("tbody tr").map((row) => row.attributes("data-rel")),
        ).toEqual(["direct", "none"]);
        await view.findAll("tbody button")[1].trigger("click");
        expect(
            view.findAll("tbody tr").map((row) => row.attributes("data-rel")),
        ).toEqual(["direct", "self"]);
    });

    it("previews the pair of a row under the mouse, fading nothing", async () => {
        vi.useFakeTimers();
        const { view } = mountLinked();
        await view
            .findAll("tbody tr")[0]
            .trigger("pointerenter", { pointerType: "mouse" });
        vi.runAllTimers();
        await view.vm.$nextTick();
        expect(
            view
                .findAll("tbody tr")
                .map((row) => row.attributes("data-preview")),
        ).toEqual(["self", undefined]);
        expect(
            view.findAll("tbody tr").map((row) => row.attributes("data-rel")),
        ).toEqual([undefined, undefined]);
    });

    it("names each row's toggle by its visible colour and material, in their languages", () => {
        const view = mountTable();
        const names = view
            .findAll("tbody button")
            .map((button) =>
                (button.attributes("aria-labelledby") ?? "")
                    .split(" ")
                    .map((id) => view.find(`[id="${id}"]`)),
            );
        expect(
            names.map((parts) => parts.map((part) => part.text()).join(" ")),
        ).toEqual(["Blue Azurite", "No colour stated Chalk"]);
        expect(
            names.map((parts) => parts.map((part) => part.attributes("lang"))),
        ).toEqual([
            ["en", "en"],
            [undefined, "en"],
        ]);
    });
});
