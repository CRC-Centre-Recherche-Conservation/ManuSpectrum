import { describe, expect, it } from "vitest";

import {
    matchingEvents,
    matchingMaterials,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/matching.ts";
import {
    label,
    mapEvent,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { EventMaterial } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

function material(id: string, matches: boolean): EventMaterial {
    return {
        id,
        name: label(id),
        reliability: null,
        characterization: uuid(500),
        matches,
    };
}

describe("matching materials", () => {
    it("keeps the materials that meet the filters", () => {
        const event = mapEvent({
            materials: [material("red", true), material("green", false)],
        });
        expect(matchingMaterials(event).map((m) => m.id)).toEqual(["red"]);
    });

    it("narrows each event, drops one with no matching material, keeps one without materials", () => {
        const all = mapEvent({ id: "all", materials: [material("red", true)] });
        const mixed = mapEvent({
            id: "mixed",
            materials: [material("red", true), material("green", false)],
        });
        const none = mapEvent({
            id: "none",
            materials: [material("green", false)],
        });
        const bare = mapEvent({ id: "bare", materials: [] });
        const shown = matchingEvents([all, mixed, none, bare]);
        expect(shown.map((event) => event.id)).toEqual([
            "all",
            "mixed",
            "bare",
        ]);
        expect(shown[0]).toBe(all);
        expect(shown[1].materials.map((m) => m.id)).toEqual(["red"]);
    });
});
