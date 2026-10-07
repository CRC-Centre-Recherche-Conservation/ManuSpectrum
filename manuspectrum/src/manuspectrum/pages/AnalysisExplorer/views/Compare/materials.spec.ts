import { describe, expect, it } from "vitest";

import {
    characterization,
    label,
    uuid,
    valueRef,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import {
    AN1,
    AN2,
    CH1,
    CH2,
    CH3,
    ITEMS,
    SYNTHESIS,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/linked.ts";
import {
    componentNode,
    pairNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";
import {
    bestConfidence,
    certaintySteps,
    groupByComponent,
    groupByPair,
    materialCounts,
    materialRecords,
    materialsSubtitle,
    materialsTitle,
    shownRecords,
    unionCanvases,
    unionComponents,
    unionEvidence,
    unionLevels,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/materials.ts";

import type {
    CharacterizationSummary,
    RankedValue,
    Ref,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";
import type { MaterialRecord } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/materials.ts";
import type { MaterialRow } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/windows.ts";

const MANTLE = (ITEMS[2] as { characterization: CharacterizationSummary })
    .characterization;

function ranked(uri: string, text: string, rank: number): RankedValue {
    return { ...valueRef(uri, text), rank };
}

const MAJOR = ranked("http://example.org/major", "Major", 0);
const MINOR = ranked("http://example.org/minor", "Minor", 1);
const TRACE = ranked("http://example.org/trace", "Trace", 2);
const FE = valueRef("http://example.org/fe", "Fe");
const PB = valueRef("http://example.org/pb", "Pb");
const S = valueRef("http://example.org/s", "S");

function component(n: number, name: string): Ref {
    return { id: uuid(900 + n), model: "component", name: label(name) };
}

function record(
    n: number,
    overrides: Partial<CharacterizationSummary> = {},
    rest: Partial<MaterialRecord> = {},
): MaterialRecord {
    const summary = characterization(n, overrides);
    return {
        id: summary.id,
        summary,
        selected: true,
        cites: [],
        canvases: [],
        components: summary.objects.filter(
            (entry) => entry.model === "component",
        ),
        ...rest,
    };
}

function row(slot: number, summary: CharacterizationSummary): MaterialRow {
    return { key: `ch:${summary.id}:-`, slot, characterization: summary };
}

describe("materialRecords", () => {
    it("lists every material of the synthesis, the Selection's own first by slot, then those citing it", () => {
        const records = materialRecords([row(2, MANTLE)], SYNTHESIS);
        expect(records.map((entry) => entry.id)).toEqual([CH1, CH2, CH3]);
        expect(records.map((entry) => entry.selected)).toEqual([
            true,
            false,
            false,
        ]);
        expect(records[1].cites).toEqual(SYNTHESIS.materials[1].evidence);
        expect(records[1].canvases).toEqual(["https://iiif.example/c1"]);
        expect(records[1].summary).toBe(SYNTHESIS.materials[1].summary);
    });

    it("orders the Selection's own materials by their first slot", () => {
        const other = characterization(9);
        const synthesis = {
            ...SYNTHESIS,
            materials: [
                ...SYNTHESIS.materials,
                {
                    ...SYNTHESIS.materials[0],
                    id: other.id,
                    summary: other,
                    selected: true,
                },
            ],
        };
        const records = materialRecords(
            [row(4, MANTLE), row(1, other), row(0, other)],
            synthesis,
        );
        expect(records.map((entry) => entry.id)).toEqual([
            other.id,
            CH1,
            CH2,
            CH3,
        ]);
    });

    it("keeps a Selection row the synthesis does not hold yet, placed by its zone", () => {
        const late = characterization(8, {
            zone: {
                canvas: "c8",
                shape: { type: "point", x: 1, y: 1 },
                source: "own",
            },
        });
        const records = materialRecords([row(5, late)], SYNTHESIS);
        expect(records.map((entry) => entry.id)).toEqual([
            late.id,
            CH1,
            CH2,
            CH3,
        ]);
        expect(records[0]).toEqual({
            id: late.id,
            summary: late,
            selected: true,
            cites: [],
            canvases: ["c8"],
            components: [],
        });
        expect(records[1].selected).toBe(true);
    });

    it("names the components a material is linked to from its objects and the coverage rows, one it cites included", () => {
        const initial = component(1, "Initial T");
        const border = component(2, "Border");
        const cited = characterization(1, {
            objects: [],
            components: [initial.id, border.id, uuid(990)],
        });
        const synthesis = {
            ...SYNTHESIS,
            coverage: [
                {
                    ...SYNTHESIS.coverage[0],
                    components: [{ component: border, counts: {} }],
                },
            ],
            materials: [],
        };
        const [entry] = materialRecords(
            [row(0, { ...cited, objects: [initial] })],
            synthesis,
        );
        expect(entry.components).toEqual([initial, border]);
    });

    it("lists the rows alone without a synthesis, once each", () => {
        const plain = characterization(3);
        const records = materialRecords(
            [row(1, plain), row(0, MANTLE), row(4, plain)],
            null,
        );
        expect(records.map((entry) => entry.id)).toEqual([MANTLE.id, plain.id]);
        expect(records[1].canvases).toEqual([]);
    });

    it("keeps of a previous synthesis only the Selection's rows and the materials citing its analyses", () => {
        const records = materialRecords([], SYNTHESIS, new Set([AN2]));
        expect(records.map((entry) => [entry.id, entry.selected])).toEqual([
            [CH3, false],
        ]);
    });

    it("never takes a material of a previous synthesis for the Selection's own once its row left", () => {
        const records = materialRecords([], SYNTHESIS, new Set([AN1]));
        expect(records.map((entry) => [entry.id, entry.selected])).toEqual([
            [CH1, false],
            [CH2, false],
        ]);
    });
});

describe("counts and filters", () => {
    const records = materialRecords([row(2, MANTLE)], SYNTHESIS);

    it("counts the Selection's own materials and those citing it", () => {
        expect(materialCounts(records)).toEqual({
            total: 3,
            selected: 1,
            citing: 2,
        });
    });

    it("leaves out the citing materials unless asked", () => {
        expect(shownRecords(records, true)).toHaveLength(3);
        expect(shownRecords(records, false).map((entry) => entry.id)).toEqual([
            CH1,
        ]);
    });

    it("titles the window and sums it up", () => {
        const identity = (text: string): string => text;
        const plural = (one: string, many: string, n: number): string =>
            n === 1 ? one : many;
        const fill = (
            message: string,
            values: Record<string, string | number>,
        ): string =>
            message.replace(/%\{(\w+)\}/g, (_, key: string) =>
                String(values[key]),
            );
        expect(materialsTitle(identity)).toBe("Materials");
        expect(
            materialsSubtitle(materialCounts(records), identity, plural, fill),
        ).toBe("3 identified materials · 1 of the Selection · 2 citing it");
        expect(
            materialsSubtitle(
                { total: 1, selected: 1, citing: 0 },
                identity,
                plural,
                fill,
            ),
        ).toBe("1 identified material");
    });
});

describe("groups", () => {
    const records = materialRecords([row(2, MANTLE)], SYNTHESIS);

    it("gathers the records under each pair of the synthesis, in its order", () => {
        const grouped = groupByPair(records, SYNTHESIS.pairs);
        expect(grouped.groups.map((group) => group.node)).toEqual([
            pairNode(
                SYNTHESIS.pairs[0].colour!.id,
                SYNTHESIS.pairs[0].material.id,
            ),
            pairNode(null, SYNTHESIS.pairs[1].material.id),
        ]);
        expect(
            grouped.groups.map((group) =>
                group.records.map((entry) => entry.id),
            ),
        ).toEqual([[CH1, CH2], [CH3]]);
        expect(grouped.groups[0].colour).toBe(SYNTHESIS.pairs[0].colour);
        expect(grouped.groups[0].name).toBe(SYNTHESIS.pairs[0].material.label);
        expect(grouped.rest).toEqual([]);
    });

    it("leaves out a pair holding none of the records shown, and lists the records no pair holds", () => {
        const loose = record(7);
        const grouped = groupByPair(
            [...shownRecords(records, false), loose],
            SYNTHESIS.pairs,
        );
        expect(grouped.groups).toHaveLength(1);
        expect(grouped.groups[0].records.map((entry) => entry.id)).toEqual([
            CH1,
        ]);
        expect(grouped.rest).toEqual([loose]);
    });

    it("gathers the records under each component they observe, a record under each", () => {
        const initial = component(1, "Initial T");
        const border = component(2, "Border");
        const first = record(1, { objects: [initial, border] });
        const second = record(2, { objects: [border] });
        const none = record(3, { objects: [] });
        const grouped = groupByComponent([first, second, none]);
        expect(grouped.groups.map((group) => group.node)).toEqual([
            componentNode(initial.id),
            componentNode(border.id),
        ]);
        expect(
            grouped.groups.map((group) =>
                group.records.map((entry) => entry.id),
            ),
        ).toEqual([[first.id], [first.id, second.id]]);
        expect(grouped.groups[1].name).toEqual(label("Border"));
        expect(grouped.rest).toEqual([none]);
        expect(unionComponents([first, second])).toEqual([initial, border]);
    });
});

describe("aggregates", () => {
    it("unions elements by level, strongest first, each element once at its strongest level", () => {
        const first = record(1, {
            elements: [
                { level: MINOR, values: [FE, S] },
                { level: MAJOR, values: [PB] },
            ],
        });
        const second = record(2, {
            elements: [
                {
                    level: null,
                    values: [valueRef("http://example.org/x", "X")],
                },
                { level: TRACE, values: [FE] },
                { level: MAJOR, values: [S] },
            ],
        });
        expect(
            unionLevels([first, second]).map((entry) => [
                entry.level?.label.value ?? null,
                entry.values.map((value) => value.label.value),
            ]),
        ).toEqual([
            ["Major", ["Pb", "S"]],
            ["Minor", ["Fe"]],
            [null, ["X"]],
        ]);
    });

    it("takes the most certain confidence, then the lowest id", () => {
        const reliable = ranked("http://example.org/reliable", "Reliable", 1);
        const caution = ranked("http://example.org/caution", "Caution", 2);
        const twin = ranked("http://example.org/a-reliable", "Also", 1);
        const materials = (confidence: RankedValue | null) => [
            {
                value: valueRef("http://example.org/v", "Vermilion"),
                confidence,
                proportion: null,
            },
        ];
        expect(bestConfidence([record(1)])).toBeNull();
        expect(
            bestConfidence([
                record(1, { materials: materials(caution) }),
                record(2, { materials: materials(reliable) }),
                record(3, { materials: materials(twin) }),
            ]),
        ).toBe(twin);
    });

    it("fills four steps for the most certain level and never fewer than one", () => {
        expect(
            [0, 1, 2, 3, 7].map((rank) =>
                certaintySteps(ranked("http://example.org/c", "C", rank)),
            ),
        ).toEqual([4, 3, 2, 1, 1]);
    });

    it("unions canvases and evidence once each, in first-seen order", () => {
        const first = record(
            1,
            {
                evidence: [
                    { id: "a2", name: label("A2") },
                    { id: "a1", name: label("A1") },
                ],
            },
            { canvases: ["c2", "c1"] },
        );
        const second = record(
            2,
            { evidence: [{ id: "a1", name: label("A1") }] },
            { canvases: ["c1", "c3"] },
        );
        expect(unionCanvases([first, second])).toEqual(["c2", "c1", "c3"]);
        expect(unionEvidence([first, second]).map((entry) => entry.id)).toEqual(
            ["a2", "a1"],
        );
    });
});
