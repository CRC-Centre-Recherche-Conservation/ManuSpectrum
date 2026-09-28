import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";

import MaterialsTable from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/components/MaterialsTable.vue";

import { LINKED_SELECTION_KEY } from "@/manuspectrum/pages/AnalysisExplorer/injection-keys.ts";
import { useExplorerStore } from "@/manuspectrum/pages/AnalysisExplorer/store/explorer.ts";
import {
    characterization,
    label,
    uuid,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    AN2,
    CH1,
    ITEMS,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    analysisNode,
    elementNode,
    materialNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { VueWrapper } from "@vue/test-utils";
import type { CharacterizationSummary } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
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

let stop: (() => void) | null = null;

beforeEach(() => {
    setActivePinia(createPinia());
});

afterEach(() => {
    stop?.();
    stop = null;
    vi.useRealTimers();
});

const MANTLE = (ITEMS[2] as { characterization: CharacterizationSummary })
    .characterization;

function mountLinked(): { view: VueWrapper; linked: LinkedSelection } {
    const started = startLinkedSelection();
    stop = started.stop;
    const summary = {
        ...MANTLE,
        elements: [
            {
                level: null,
                values: [
                    valueRef("http://example.org/cu", "Copper"),
                    valueRef("http://example.org/xx", "Unknown"),
                ],
            },
        ],
    };
    const view = mount(MaterialsTable, {
        props: {
            rows: [{ key: `ch:${CH1}:-`, slot: 2, characterization: summary }],
        },
        global: {
            provide: { [LINKED_SELECTION_KEY as symbol]: started.linked },
        },
    });
    return { view, linked: started.linked };
}

function chip(view: VueWrapper, text: string) {
    return view
        .findAll("button.linked-chip")
        .find((button) => button.text() === text)!;
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
            "Blue Dark",
            "Lapis lazuli Certain Lead white",
            "Paint layer",
            "Major: Si Al Pb",
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
            "— Not stated",
            "— Not stated",
            "— Not stated",
            "— Not stated",
        ]);
        const none = wrapper.findAll(".none")[0];
        expect(none.attributes("aria-label")).toBeUndefined();
        expect(none.attributes("aria-hidden")).toBe("true");
        expect(none.element.nextElementSibling?.className).toBe(
            "visually-hidden",
        );
    });

    it("makes a row's name the toggle of its record, pressed and outlined once selected", async () => {
        const { view } = mountLinked();
        const row = view.find("tbody tr");
        expect(row.attributes("data-rel")).toBeUndefined();
        const record = view.find("button.record");
        expect(record.attributes("aria-pressed")).toBe("false");
        await record.trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            materialNode(CH1),
        ]);
        expect(row.attributes("data-rel")).toBe("self");
        expect(record.attributes("aria-pressed")).toBe("true");
    });

    it("turns colours, materials, elements with a symbol and analyses cited into toggles", async () => {
        const { view } = mountLinked();
        expect(
            view.findAll("button.linked-chip").map((button) => button.text()),
        ).toEqual(["Blue", "Azurite", "Copper", "MS1_f12_XRF_01"]);
        expect(view.find(".plain").text()).toBe("Unknown");
        await chip(view, "Copper").trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            elementNode("Cu"),
        ]);
        expect(chip(view, "Copper").attributes("aria-pressed")).toBe("true");
        expect(chip(view, "Copper").attributes("data-rel")).toBe("self");
    });

    it("highlights a row linked to the selection and its linked values, and marks the others unlinked", async () => {
        const { view, linked } = mountLinked();
        linked.toggle(elementNode("Cu"));
        await view.vm.$nextTick();
        expect(view.find("tbody tr").attributes("data-rel")).toBe("direct");
        expect(chip(view, "Blue").attributes("data-rel")).toBe("direct");
        expect(chip(view, "MS1_f12_XRF_01").attributes("data-rel")).toBe(
            "evidence",
        );
        linked.clear();
        linked.toggle(analysisNode(AN2));
        await view.vm.$nextTick();
        expect(view.find("tbody tr").attributes("data-rel")).toBe("none");
        expect(chip(view, "Blue").attributes("data-rel")).toBe("none");
        expect(useExplorerStore().compare.selection).toEqual([
            analysisNode(AN2),
        ]);
    });

    it("previews a row's record under the mouse without marking anything unlinked", async () => {
        vi.useFakeTimers();
        const { view } = mountLinked();
        const row = view.find("tbody tr");
        await row.trigger("pointerenter", { pointerType: "mouse" });
        vi.runAllTimers();
        await view.vm.$nextTick();
        expect(row.attributes("data-preview")).toBe("self");
        expect(chip(view, "MS1_f12_XRF_01").attributes("data-preview")).toBe(
            "evidence",
        );
        expect(row.attributes("data-rel")).toBeUndefined();
        await row.trigger("pointerleave", { pointerType: "mouse" });
        vi.runAllTimers();
        await view.vm.$nextTick();
        expect(row.attributes("data-preview")).toBeUndefined();
    });
});
