import { describe, expect, it } from "vitest";

import {
    MULTIPLES_PER_PAGE,
    byCentury,
    byMaterial,
    centuriesIn,
    pageOf,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/multiples.ts";
import {
    label,
    mapEvent,
    mapPlace,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type { EventMaterial } from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

const none = new Set<string>();

function material(id: string): EventMaterial {
    return {
        id,
        name: label(id),
        reliability: null,
        characterization: uuid(500),
    };
}

const places = {
    [uuid(10)]: mapPlace(),
    [uuid(11)]: mapPlace({
        id: uuid(11),
        name: label("Lyon"),
        lngLat: [4.8, 45.7],
    }),
};

function carrying(id: string, component: number, place = uuid(10)) {
    return mapEvent({
        id: `${id}${component}${place}`,
        place,
        component: { id: uuid(component), name: label(`c${component}`) },
        materials: [material(id)],
    });
}

describe("small multiples", () => {
    it("sorts materials by components, filled where attested, hollow where only analysed", () => {
        const events = [
            carrying("few", 20),
            carrying("many", 21),
            carrying("many", 22),
            mapEvent({ id: "plain", place: uuid(11) }),
        ];
        const maps = byMaterial(events, places, ["few", "many"], none);
        expect(maps.map((m) => m.uri)).toEqual(["many", "few"]);
        const dots = Object.fromEntries(maps[0].dots.map((d) => [d.id, d]));
        expect(dots[uuid(10)].attested).toBe(true);
        expect(dots[uuid(10)].size).toBeCloseTo(Math.SQRT2);
        expect(dots[uuid(11)].attested).toBe(false);
    });

    it("puts the followed materials first, in slot order", () => {
        const events = [
            carrying("few", 20),
            carrying("many", 21),
            carrying("many", 22),
            carrying("mid", 23),
            carrying("mid", 24),
            carrying("rare", 25),
        ];
        const maps = byMaterial(
            events,
            places,
            ["few", "many", "mid", "rare"],
            none,
            [
                { uri: "rare", slot: 1 },
                { uri: "few", slot: 3 },
            ],
        );
        expect(maps.map((m) => m.uri)).toEqual(["rare", "few", "many", "mid"]);
    });

    it("pages by twelve", () => {
        const items = Array.from({ length: 25 }, (_, i) => i);
        expect(MULTIPLES_PER_PAGE).toBe(12);
        expect(pageOf(items, 0)).toHaveLength(12);
        expect(pageOf(items, 2)).toEqual([24]);
        expect(pageOf(items, 9)).toEqual([24]);
    });

    it("puts an event of 1290–1310 in both centuries", () => {
        const event = mapEvent({
            date: { start: 1290, end: 1310, approximate: false },
            materials: [material("m")],
        });
        const maps = byCentury(
            [event],
            places,
            [{ uri: "m", slot: 2 }],
            none,
            [1250, 1420],
        );
        expect(maps.map((m) => [m.century, m.dots.length])).toEqual([
            [12, 1],
            [13, 1],
            [14, 0],
        ]);
        expect(maps[1].dots[0].slots).toEqual([2]);
    });

    it("lists the centuries of a range", () => {
        expect(centuriesIn([1250, 1420])).toEqual([12, 13, 14]);
    });
});
