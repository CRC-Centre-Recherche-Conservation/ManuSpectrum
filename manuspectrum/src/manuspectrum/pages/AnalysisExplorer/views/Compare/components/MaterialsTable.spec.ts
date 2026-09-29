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
    AN1,
    AN2,
    AZURITE,
    BLUE,
    CH1,
    CH2,
    ITEMS,
    SYNTHESIS,
    startLinkedSelection,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    analysisNode,
    colourNode,
    componentNode,
    elementNode,
    materialNode,
    pairNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import { materialRecords } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/materials.ts";

import type { VueWrapper } from "@vue/test-utils";
import type {
    AnalysisHit,
    CharacterizationSummary,
    Item,
    RankedValue,
    Ref,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { LinkedSelection } from "@/manuspectrum/pages/AnalysisExplorer/composables/useLinkedSelection.ts";
import type { MaterialRecord } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/materials.ts";

const MANTLE = (ITEMS[2] as { characterization: CharacterizationSummary })
    .characterization;
const ANALYSES = ITEMS.flatMap((item: Item) =>
    item.kind === "characterization" ? [] : [item.analysis],
) as AnalysisHit[];
const RELIABLE: RankedValue = {
    ...valueRef("http://example.org/reliable", "Reliable"),
    rank: 1,
};
const CAUTION: RankedValue = {
    ...valueRef("http://example.org/caution", "Use with caution"),
    rank: 2,
};
const MAJOR: RankedValue = {
    ...valueRef("http://example.org/major", "Major"),
    rank: 0,
};
const BORDER: Ref = {
    id: uuid(951),
    model: "component",
    name: label("Border"),
};

/** The Selection's mantle (A3, reliable, Cu major, an unknown element) and the synthesis' two citing materials. */
const MANTLE_FULL: CharacterizationSummary = {
    ...MANTLE,
    materials: [{ value: AZURITE, confidence: RELIABLE, proportion: null }],
    layers: [valueRef("http://example.org/paint", "Paint layer")],
    elements: [
        {
            level: MAJOR,
            values: [
                valueRef("http://example.org/cu", "Copper"),
                valueRef("http://example.org/xx", "Unknown"),
            ],
        },
    ],
};

function linkedRecords(): MaterialRecord[] {
    const synthesis = {
        ...SYNTHESIS,
        materials: SYNTHESIS.materials.map((material, index) =>
            index === 0
                ? { ...material, summary: MANTLE_FULL }
                : index === 1
                  ? {
                        ...material,
                        summary: {
                            ...material.summary,
                            materials: [
                                {
                                    value: AZURITE,
                                    confidence: CAUTION,
                                    proportion: null,
                                },
                            ],
                        },
                    }
                  : material,
        ),
    };
    return materialRecords(
        [{ key: `ch:${CH1}:-`, slot: 2, characterization: MANTLE_FULL }],
        synthesis,
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

function mountLinked(
    records: MaterialRecord[] = linkedRecords(),
    attachTo: HTMLElement | undefined = undefined,
): {
    view: VueWrapper;
    linked: LinkedSelection;
} {
    const started = startLinkedSelection();
    stop = started.stop;
    const view = mount(MaterialsTable, {
        attachTo,
        props: {
            records,
            pairs: SYNTHESIS.pairs,
            canvases: SYNTHESIS.canvases,
            analyses: ANALYSES,
        },
        global: {
            provide: { [LINKED_SELECTION_KEY as symbol]: started.linked },
        },
    });
    return { view, linked: started.linked };
}

function mountPlain(records: MaterialRecord[]): VueWrapper {
    return mount(MaterialsTable, {
        props: { records, pairs: [], canvases: [], analyses: [] },
    });
}

function names(view: VueWrapper): string[] {
    return view.findAll("tbody th .main").map((name) => name.text());
}

function column(view: VueWrapper, index: number): string[] {
    return view
        .findAll("tbody tr")
        .map((row) => row.findAll("th, td")[index].text());
}

function chip(view: VueWrapper, text: string) {
    return view
        .findAll("button.linked-chip")
        .find((button) => button.text() === text)!;
}

describe("MaterialsTable", () => {
    it("heads its columns, the first one by the grouping", async () => {
        const { view } = mountLinked();
        expect(view.findAll("thead th").map((cell) => cell.text())).toEqual([
            "Identified material",
            "Certainty",
            "Colour",
            "Component",
            "Folio",
            "Elements",
            "Evidence",
            "Selection",
        ]);
        useExplorerStore().setMaterialsGrouping("pair");
        await view.vm.$nextTick();
        expect(view.find("thead th").text()).toBe("Colour × material");
        useExplorerStore().setMaterialsGrouping("component");
        await view.vm.$nextTick();
        expect(view.find("thead th").text()).toBe("Component");
    });

    it("lists every identified material of the synthesis, the Selection's own first, each with its slot or the analyses it cites", () => {
        const { view } = mountLinked();
        expect(names(view)).toEqual(["Azurite", "Azurite", "Chalk"]);
        expect(view.find("tbody th .rest").text()).toBe(
            "Paint layer · Manuscript 1",
        );
        expect(view.find("tbody th button").attributes("title")).toBe(
            "Blue of the mantle",
        );
        expect(view.find("tbody th").attributes("scope")).toBe("row");
        expect(column(view, 7)).toEqual(["A3", "cites A1", "cites A2"]);
        expect(view.findAll("tbody .tag")[1].attributes("title")).toBe(
            "Not in the Selection: cites A1",
        );
        expect(view.find(".tag.sel").text()).toBe("A3");
        expect(column(view, 4)).toEqual(["f. 12r", "f. 12r", "f. 12v"]);
    });

    it("draws the certainty on four ordered steps with its label", () => {
        const { view } = mountLinked();
        const scale = view.find("tbody .certainty-scale");
        expect(scale.text()).toBe("Reliable");
        expect(scale.attributes("title")).toBe("Reliable (3 of 4)");
        expect(
            scale.findAll(".steps i").map((step) => step.classes("on")),
        ).toEqual([true, true, true, false]);
        expect(column(view, 1)[2]).toBe("—Not stated");
    });

    it("shows the colours with a neutral swatch, as toggles of their node", async () => {
        const { view } = mountLinked();
        const blue = chip(view, "Blue");
        expect(blue.find(".swatch").exists()).toBe(true);
        await blue.trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            colourNode(BLUE.id),
        ]);
        expect(column(view, 2)[2]).toBe("—Not stated");
    });

    it("leaves out the materials citing the Selection when the box is unticked", async () => {
        const { view } = mountLinked();
        const box = view.find(".citing input");
        expect(view.find(".citing").text()).toBe(
            "Also the materials citing an analysis of the Selection (2)",
        );
        expect((box.element as HTMLInputElement).checked).toBe(true);
        await box.setValue(false);
        expect(names(view)).toEqual(["Azurite"]);
    });

    it("says so when only citing materials remain and the box is unticked", async () => {
        const citing = linkedRecords().filter((record) => !record.selected);
        const { view } = mountLinked(citing);
        await view.find(".citing input").setValue(false);
        expect(view.find(".empty").text()).toBe(
            "No identified material of the Selection itself.",
        );
        expect(view.find("table").exists()).toBe(false);
    });

    it("has no box when no material only cites the Selection", () => {
        const view = mountPlain([
            {
                id: MANTLE.id,
                summary: MANTLE,
                selected: true,
                cites: [],
                canvases: [],
            },
        ]);
        expect(view.find(".citing").exists()).toBe(false);
    });

    it("groups by colour × material, each group folded to its aggregate, unfolding to its records", async () => {
        const { view } = mountLinked();
        const buttons = view.findAll(".segmented button");
        expect(buttons.map((button) => button.text())).toEqual([
            "Record",
            "Colour × material",
            "Component",
        ]);
        expect(view.find(".segmented").attributes("role")).toBe("group");
        await buttons[1].trigger("click");
        expect(useExplorerStore().materialsGrouping).toBe("pair");
        expect(
            buttons.map((button) => button.attributes("aria-pressed")),
        ).toEqual(["false", "true", "false"]);
        expect(names(view)).toEqual(["Blue × Azurite", "Chalk"]);
        const group = view.find("tbody tr.group");
        expect(group.find(".rest").text()).toBe("2 identified materials");
        expect(group.find(".certainty-scale").text()).toContain("Reliable");
        expect(group.find(".certainty-scale .best").text()).toBe("best");
        expect(group.find(".selection").text()).toBe(
            "1+11 of the Selection · 1 citing it",
        );
        const caret = group.find(".caret");
        expect(caret.attributes("aria-expanded")).toBe("false");
        expect(caret.attributes("aria-label")).toBe(
            "Identified materials of Blue × Azurite",
        );
        await caret.trigger("click");
        expect(caret.attributes("aria-expanded")).toBe("true");
        expect(names(view)).toEqual([
            "Blue × Azurite",
            "Azurite",
            "Azurite",
            "Chalk",
        ]);
        expect(
            view.findAll("tbody tr").map((row) => row.classes("nested")),
        ).toEqual([false, true, true, false]);
        await view.find("tbody tr.group th button.toggle").trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            pairNode(BLUE.id, AZURITE.id),
        ]);
        await caret.trigger("click");
        expect(names(view)).toEqual(["Blue × Azurite", "Chalk"]);
    });

    it("keeps the grouping chosen for the tab", async () => {
        useExplorerStore().setMaterialsGrouping("pair");
        const { view } = mountLinked();
        expect(names(view)).toEqual(["Blue × Azurite", "Chalk"]);
    });

    it("groups by component, a group listing its materials, the records without one after", async () => {
        useExplorerStore().setMaterialsGrouping("component");
        const border = (n: number, name: string): MaterialRecord => {
            const summary = characterization(n, {
                objects: [BORDER],
                colours: [valueRef(`http://example.org/c${n}`, `C${n}`)],
                materials: [
                    {
                        value: valueRef(`http://example.org/m${n}`, name),
                        confidence: null,
                        proportion: null,
                    },
                ],
            });
            return {
                id: summary.id,
                summary,
                selected: n === 1,
                cites: [],
                canvases: [],
            };
        };
        const loose = characterization(3, { objects: [] });
        const view = mountPlain([
            border(1, "Vermilion"),
            border(2, "Minium"),
            {
                id: loose.id,
                summary: loose,
                selected: true,
                cites: [],
                canvases: [],
            },
        ]);
        expect(names(view)).toEqual(["Border", "Vermilion"]);
        expect(
            view.findAll("thead th").map((heading) => heading.text()),
        ).toEqual([
            "Component",
            "Certainty",
            "Colour",
            "Materials",
            "Folio",
            "Elements",
            "Evidence",
            "Selection",
        ]);
        const group = view.find("tbody tr.group");
        expect(group.findAll("td")[2].text()).toBe("Vermilion, Minium");
        expect(group.findAll("td")[1].text()).toBe("C1C2");
        await group.find(".caret").trigger("click");
        expect(names(view)).toEqual([
            "Border",
            "Vermilion",
            "Minium",
            "Vermilion",
        ]);
        const nested = view.findAll("tbody tr.nested")[0];
        await nested
            .findAll("td")[2]
            .find("button.linked-chip")
            .trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            componentNode(BORDER.id),
        ]);
    });

    it("shows a component or group the focus cannot hold as plain text", async () => {
        useExplorerStore().setMaterialsGrouping("component");
        const summary = { ...MANTLE_FULL, objects: [BORDER] };
        const { view } = mountLinked([
            {
                id: summary.id,
                summary,
                selected: true,
                cites: [],
                canvases: [],
            },
        ]);
        const group = view.find("tbody tr.group");
        expect(group.find("button.toggle").exists()).toBe(false);
        expect(group.find(".plain-name .main").text()).toBe("Border");
        await group.find(".caret").trigger("click");
        const cell = view.find("tbody tr.nested").findAll("td")[2];
        expect(cell.find("button").exists()).toBe(false);
        expect(cell.text()).toBe("Border");
    });

    it("makes a record's name the toggle of its record, pressed and outlined once selected", async () => {
        const { view } = mountLinked();
        const row = view.find("tbody tr");
        expect(row.attributes("data-rel")).toBeUndefined();
        const record = view.find("tbody th button.toggle");
        expect(record.classes()).toContain("ms-focus");
        expect(record.attributes("aria-pressed")).toBe("false");
        await record.trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            materialNode(CH1),
        ]);
        expect(row.attributes("data-rel")).toBe("self");
        expect(record.attributes("aria-pressed")).toBe("true");
        expect(record.attributes("data-rel")).toBe("self");
    });

    it("gives the elements by level, those with a symbol as toggles", async () => {
        const { view } = mountLinked();
        const levels = view.find("tbody .element-levels");
        expect(levels.find(".level").text()).toBe("Major");
        expect(levels.find(".plain").text()).toBe("Unknown");
        const copper = chip(view, "Cu");
        expect(copper.attributes("title")).toBe("Copper");
        await copper.trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            elementNode("Cu"),
        ]);
        expect(copper.attributes("aria-pressed")).toBe("true");
        expect(column(view, 5)[1]).toBe("—Not stated");
    });

    it("counts the evidence with its techniques and unfolds the analyses as toggles", async () => {
        const { view } = mountLinked();
        const evidence = view.find("tbody .material-evidence");
        const expander = evidence.find(".expander");
        expect(expander.text()).toContain("1 analysis");
        expect(expander.attributes("aria-expanded")).toBe("false");
        expect(evidence.find(".technique").text()).toBe("XRF");
        expect(evidence.find(".analyses").exists()).toBe(false);
        await expander.trigger("click");
        expect(expander.attributes("aria-expanded")).toBe("true");
        expect(expander.attributes("aria-controls")).toBe(
            evidence.find(".analyses").attributes("id"),
        );
        await chip(view, "MS1_f12_XRF_01").trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            analysisNode(AN1),
        ]);
    });

    it("counts the techniques of the evidence and leaves unknown analyses plain", async () => {
        const summary = {
            ...MANTLE_FULL,
            evidence: [
                { id: AN1, name: label("MS1_f12_XRF_01") },
                { id: uuid(199), name: label("Outside") },
            ],
        };
        const { view } = mountLinked([
            {
                id: summary.id,
                summary,
                selected: true,
                cites: [AN1],
                canvases: [],
            },
        ]);
        await view.find(".expander").trigger("click");
        expect(view.find(".expander").text()).toContain("2 analyses");
        expect(view.find(".analyses .plain").text()).toBe("Outside");
    });

    it("sums up a group's evidence, techniques counted", async () => {
        useExplorerStore().setMaterialsGrouping("pair");
        const records = linkedRecords();
        records[1] = {
            ...records[1],
            summary: {
                ...records[1].summary,
                evidence: [
                    { id: AN1, name: label("MS1_f12_XRF_01") },
                    { id: AN2, name: label("MS1_f12_XRF_02") },
                ],
            },
        };
        const { view } = mountLinked(records);
        const evidence = view.find("tbody tr.group .material-evidence");
        expect(evidence.find(".expander").text()).toContain("2 analyses");
        expect(evidence.findAll(".technique").map((tag) => tag.text())).toEqual(
            ["XRF", "Raman"],
        );
        expect(column(view, 7)[1]).toBe("0+10 of the Selection · 1 citing it");
    });

    it("marks a draft", () => {
        const draft = { ...MANTLE, unpublished: true };
        const view = mountPlain([
            {
                id: draft.id,
                summary: draft,
                selected: false,
                cites: [],
                canvases: ["c9"],
            },
        ]);
        expect(view.find("tbody .badge").text()).toBe("Draft");
        expect(column(view, 4)).toEqual(["1 folio"]);
        expect(column(view, 7)).toEqual([""]);
        expect(view.find("tbody th .main").text()).toBe("Azurite");
    });

    it("names a record without a material by its name, and counts the folios it cannot name", () => {
        const bare = characterization(4, { materials: [] });
        const view = mount(MaterialsTable, {
            props: {
                records: [
                    {
                        id: bare.id,
                        summary: bare,
                        selected: true,
                        cites: [],
                        canvases: ["c1", "c2"],
                    },
                ],
                pairs: [],
                canvases: [{ ...SYNTHESIS.canvases[0], canvas: "c1" }],
                analyses: [],
            },
        });
        expect(view.find("tbody th .main").text()).toBe("Characterization 4");
        expect(column(view, 4)).toEqual(["f. 12r, 1 other folio"]);
    });

    it("highlights the rows linked to the focus and marks the others unlinked", async () => {
        const { view, linked } = mountLinked();
        linked.toggle(analysisNode(AN2));
        await view.vm.$nextTick();
        expect(
            view.findAll("tbody tr").map((row) => row.attributes("data-rel")),
        ).toEqual(["none", "none", "evidence"]);
        expect(view.findAll("tbody tr")[2].attributes("style")).toContain(
            "--bar",
        );
        expect(chip(view, "Blue").attributes("data-rel")).toBe("none");
    });

    it("previews a row's node under the mouse without marking anything unlinked", async () => {
        vi.useFakeTimers();
        const { view } = mountLinked(linkedRecords(), document.body);
        const row = view.find("tbody tr");
        await row.trigger("pointerenter", { pointerType: "mouse" });
        vi.runAllTimers();
        await view.vm.$nextTick();
        expect(row.attributes("data-preview")).toBe("self");
        expect(row.attributes("data-rel")).toBeUndefined();
        await row.trigger("pointerleave", { pointerType: "mouse" });
        vi.runAllTimers();
        await view.vm.$nextTick();
        expect(row.attributes("data-preview")).toBeUndefined();
        view.unmount();
    });

    it("toggles through the store outside a Compare view", async () => {
        const view = mountPlain(linkedRecords());
        await view.findAll("tbody th button.toggle")[1].trigger("click");
        expect(useExplorerStore().compare.selection).toEqual([
            materialNode(CH2),
        ]);
    });
});
