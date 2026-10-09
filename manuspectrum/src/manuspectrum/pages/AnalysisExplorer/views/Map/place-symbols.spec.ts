import { describe, expect, it } from "vitest";

import {
    attestationWeight,
    featureStates,
    inBrush,
    lowLevels,
    summarisePlaces,
    withoutLow,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/place-symbols.ts";
import {
    label,
    mapEvent,
    mapPlace,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { EventMaterial } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const LOW = new Set(["low"]);

function material(id: string, reliability: string | null): EventMaterial {
    return { id, name: label(id), reliability, characterization: uuid(500) };
}

const places = {
    [uuid(10)]: mapPlace(),
    [uuid(11)]: mapPlace({
        id: uuid(11),
        name: label("Lyon"),
        geometryKind: "area",
    }),
};

describe("place symbols", () => {
    it("keeps an overlapping event under a brush and drops a disjoint one", () => {
        const event = mapEvent({
            date: { start: 1301, end: 1400, approximate: false },
        });
        expect(inBrush(event, [1390, 1500])).toBe(true);
        expect(inBrush(event, [1401, 1500])).toBe(false);
    });

    it("drops an undated event under a brush and keeps it without one", () => {
        const event = mapEvent({
            date: { start: null, end: null, approximate: false },
        });
        expect(inBrush(event, [1200, 1500])).toBe(false);
        expect(inBrush(event, null)).toBe(true);
    });

    it("reads the low levels off the certainty scale", () => {
        const level = (id: string, rank: number) => ({
            id,
            uri: id,
            label: label(id),
            rank,
        });
        expect(
            lowLevels({
                levels: [level("a", 0), level("b", 2), level("c", 3)],
            }),
        ).toEqual(new Set(["b", "c"]));
    });

    it("drops the low materials", () => {
        const [event] = withoutLow(
            [
                mapEvent({
                    materials: [material("m", "low"), material("n", null)],
                }),
            ],
            LOW,
        );
        expect(event.materials.map((m) => m.id)).toEqual(["n"]);
    });

    it("counts distinct documents and components and skips unplaced events", () => {
        const summaries = summarisePlaces(
            [
                mapEvent({
                    id: "a",
                    component: { id: uuid(20), name: label("c") },
                }),
                mapEvent({
                    id: "b",
                    component: { id: uuid(20), name: label("c") },
                }),
                mapEvent({
                    id: "c",
                    document: { id: uuid(2), name: label("B") },
                }),
                mapEvent({ id: "d", place: null }),
                mapEvent({ id: "e", place: uuid(99) }),
            ],
            places,
            [],
            LOW,
        );
        expect([...summaries.keys()]).toEqual([uuid(10)]);
        const paris = summaries.get(uuid(10));
        expect(paris?.documents.size).toBe(2);
        expect(paris?.components.size).toBe(1);
        expect(paris?.events).toHaveLength(3);
    });

    it("marks a followed material pale when all its attestations are low and firm otherwise", () => {
        const tracked = [
            { uri: "m", slot: 1 },
            { uri: "n", slot: 2 },
        ];
        const summaries = summarisePlaces(
            [
                mapEvent({
                    materials: [material("m", "low"), material("n", "low")],
                }),
                mapEvent({ id: "b", materials: [material("n", null)] }),
            ],
            places,
            tracked,
            LOW,
        );
        expect(summaries.get(uuid(10))?.tracked).toEqual(
            new Map([
                [1, "pale"],
                [2, "firm"],
            ]),
        );
    });

    it("dashes an area place and a place known only through its parent", () => {
        const summaries = summarisePlaces(
            [
                mapEvent({ place: uuid(11) }),
                mapEvent({ id: "b", placeSource: "parent" }),
            ],
            places,
            [],
            LOW,
        );
        expect(summaries.get(uuid(11))?.dashed).toBe(true);
        expect(summaries.get(uuid(10))?.dashed).toBe(true);
        const mixed = summarisePlaces(
            [
                mapEvent({ placeSource: "parent" }),
                mapEvent({ id: "b", placeSource: "own" }),
            ],
            places,
            [],
            LOW,
        );
        expect(mixed.get(uuid(10))?.dashed).toBe(false);
    });

    it("gives the feature state per slot and dims under all a place lacking a slot", () => {
        const tracked = [
            { uri: "a", slot: 1 },
            { uri: "c", slot: 3 },
            { uri: "d", slot: 4 },
        ];
        const summary = summarisePlaces(
            [
                mapEvent({
                    materials: [material("a", null), material("c", "low")],
                }),
            ],
            places,
            [
                { uri: "a", slot: 1 },
                { uri: "b", slot: 2 },
                { uri: "c", slot: 3 },
            ],
            LOW,
        ).get(uuid(10));
        if (!summary) throw new Error("no summary");
        const two = [
            { uri: "a", slot: 1 },
            { uri: "b", slot: 2 },
            { uri: "c", slot: 3 },
        ];
        expect(featureStates(summary, two, "any")).toEqual({
            t1: 1,
            t2: 0,
            t3: 2,
            t4: 0,
            dim: false,
        });
        expect(featureStates(summary, two, "all").dim).toBe(true);
        expect(featureStates(summary, tracked.slice(0, 1), "all").dim).toBe(
            false,
        );
    });

    it("weighs a document and a component carrying the uri, each half when only low", () => {
        const component = { id: uuid(20), name: label("c") };
        const firm = [
            mapEvent({ component, materials: [material("m", null)] }),
        ];
        const pale = [
            mapEvent({ component, materials: [material("m", "low")] }),
        ];
        expect(attestationWeight(firm, "m", LOW)).toBe(2);
        expect(attestationWeight(pale, "m", LOW)).toBe(1);
        expect(attestationWeight(firm, "zzz", LOW)).toBe(0);
    });
});
