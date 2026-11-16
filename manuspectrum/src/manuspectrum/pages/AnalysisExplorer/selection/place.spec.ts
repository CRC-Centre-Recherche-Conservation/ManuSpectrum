import { describe, expect, it } from "vitest";

import {
    placeOf,
    placesOf,
} from "@/manuspectrum/pages/AnalysisExplorer/selection/place.ts";
import {
    analysisHit,
    characterization,
    fileEntry,
    imagingEntry,
    label,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";
import { buildGraph } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/graph.ts";
import {
    analysisNode,
    materialNode,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/linked/node-id.ts";

import type { Item } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const DOC_A = { id: uuid(1), model: "document", name: label("Manuscript A") };
const DOC_B = { id: uuid(2), model: "document", name: label("Manuscript B") };
const COMPONENT = { id: uuid(3), model: "component", name: label("Initial") };
const HIT = analysisHit(1, { canvas: "https://example.org/canvas/1" });

const ANALYSIS: Item = {
    key: "an",
    kind: "analysis",
    analysis: HIT,
    excitation: null,
    files: [],
};
const MATERIAL = (overrides = {}): Item => ({
    key: "ch",
    kind: "characterization",
    characterization: characterization(1, overrides),
});

describe("placeOf", () => {
    it("places an analysis, one of its files and an imaging layer on the analysis page, focused on the analysis", () => {
        const expected = {
            document: uuid(1),
            canvas: "https://example.org/canvas/1",
            focus: { kind: "analysis", id: HIT.id },
        };
        expect(placeOf(ANALYSIS)).toEqual(expected);
        expect(
            placeOf({
                key: "af",
                kind: "analysis-file",
                analysis: HIT,
                excitation: null,
                file: fileEntry(),
            }),
        ).toEqual(expected);
        expect(
            placeOf({
                key: "im",
                kind: "imaging",
                analysis: HIT,
                file: imagingEntry(),
            }),
        ).toEqual(expected);
    });

    it("keeps a null canvas for an analysis with no page", () => {
        expect(
            placeOf({ ...ANALYSIS, analysis: analysisHit(2) } as Item)?.canvas,
        ).toBeNull();
    });

    it("places a material in its first object that is not a component, on the page of its zone", () => {
        const item = MATERIAL({
            objects: [COMPONENT, DOC_A, DOC_B],
            zone: { canvas: "c1", shape: {}, source: "own" },
        });
        expect(placeOf(item)).toEqual({
            document: uuid(1),
            canvas: "c1",
            focus: {
                kind: "characterization",
                id: (item as { characterization: { id: string } })
                    .characterization.id,
            },
        });
        expect(placesOf(item).map((place) => place.document)).toEqual([
            uuid(1),
            uuid(2),
        ]);
    });

    it("gives a material with no zone a null canvas", () => {
        expect(placeOf(MATERIAL({ objects: [DOC_A] }))?.canvas).toBeNull();
    });

    it("gives a material known only through components no place", () => {
        expect(placeOf(MATERIAL({ objects: [COMPONENT] }))).toBeNull();
        expect(placesOf(MATERIAL())).toEqual([]);
    });

    it("agrees with the linked graph's places", () => {
        const material = MATERIAL({
            objects: [DOC_A, DOC_B],
            zone: { canvas: "c1", shape: {}, source: "own" },
        }) as Extract<Item, { kind: "characterization" }>;
        const graph = buildGraph({
            basket: [
                { key: "an", kind: "analysis", slot: 0 },
                { key: "ch", kind: "characterization", slot: 1 },
            ],
            byKey: new Map<string, Item>([
                ["an", ANALYSIS],
                ["ch", material],
            ]),
            synthesis: null,
        });
        for (const [node, item] of [
            [analysisNode(HIT.id), ANALYSIS],
            [materialNode(material.characterization.id), material],
        ] as const) {
            expect(graph.places.get(node)).toEqual(
                placesOf(item).map(({ document, canvas }) => ({
                    document,
                    canvas,
                })),
            );
        }
    });
});
