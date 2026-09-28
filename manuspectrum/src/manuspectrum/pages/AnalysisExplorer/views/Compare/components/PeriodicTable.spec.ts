import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import PeriodicTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/PeriodicTable.vue";

import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import { valueRef } from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    CH3,
    SYNTHESIS,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    elementNode,
    materialNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";

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
    return mount(PeriodicTable, { props: { elements: ELEMENTS, disabled } });
}

function mountLinked(): { view: VueWrapper; linked: LinkedSelection } {
    const started = startLinkedSelection();
    stop = started.stop;
    const view = mount(PeriodicTable, {
        props: { elements: SYNTHESIS.elements },
        global: {
            provide: { [LINKED_SELECTION_KEY as symbol]: started.linked },
        },
    });
    return { view, linked: started.linked };
}

function gridRel(view: VueWrapper, attribute: string): (string | undefined)[] {
    return view
        .findAll(".grid button")
        .map((button) => button.attributes(attribute));
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

    it("selects the element clicked and presses it everywhere it is shown", async () => {
        const view = mountTable();
        await view.find(".list button").trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            elementNode("Cu"),
        ]);
        expect(
            view
                .findAll(".grid button")
                .map((button) => button.attributes("aria-pressed")),
        ).toEqual(["true", "false"]);
    });

    it("selects nothing while it is disabled", async () => {
        const view = mountTable(true);
        await view.find(".grid button").trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([]);
    });

    it("rings the elements linked to the selection and marks the others unlinked", async () => {
        const { view, linked } = mountLinked();
        expect(gridRel(view, "data-rel")).toEqual([undefined, undefined]);
        linked.toggle(materialNode(CH3));
        await view.vm.$nextTick();
        expect(
            view.findAll(".grid button").map((button) => button.text()),
        ).toEqual(["Ca1", "Cu2"]);
        expect(gridRel(view, "data-rel")).toEqual(["direct", "none"]);
    });

    it("previews what an element under the mouse links", async () => {
        vi.useFakeTimers();
        const { view } = mountLinked();
        await view
            .findAll(".grid button")[1]
            .trigger("pointerenter", { pointerType: "mouse" });
        vi.runAllTimers();
        await view.vm.$nextTick();
        expect(gridRel(view, "data-preview")).toEqual([undefined, "self"]);
        expect(gridRel(view, "data-rel")).toEqual([undefined, undefined]);
    });
});
