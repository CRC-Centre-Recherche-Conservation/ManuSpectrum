import { describe, expect, it } from "vitest";

import {
    MINI_HEIGHT,
    MINI_WIDTH,
    MULTIPLES_PER_PAGE,
    byCentury,
    byMaterial,
    centuriesIn,
    pageOf,
    snapshotFrame,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/multiples.ts";
import {
    fitAspect,
    project,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/geo.ts";
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
        colours: [],
        matches: true,
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

    it("drops a material without an attested mapped place, and titles an unnamed one by its uri", () => {
        const unnamed = carrying("bare", 26);
        unnamed.materials[0].name = { value: "", lang: "" };
        const events = [
            carrying("kept", 20),
            mapEvent({
                id: "unplaced",
                place: null,
                placeSource: null,
                materials: [material("nowhere")],
            }),
            unnamed,
        ];
        const maps = byMaterial(
            events,
            places,
            ["kept", "absent", "nowhere", "bare"],
            none,
        );
        expect(maps.map((m) => [m.uri, m.title?.value, m.places])).toEqual([
            ["bare", "bare", 1],
            ["kept", "kept", 1],
        ]);
    });

    it("drops a century without an attested place", () => {
        const maps = byCentury(
            [carrying("m", 20)],
            places,
            [],
            none,
            [1250, 1420],
        );
        expect(maps.map((m) => m.century)).toEqual([13]);
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

    it("counts the places and documents that attest a material, and marks attributed places dashed", () => {
        const regional = {
            ...places,
            [uuid(12)]: mapPlace({
                id: uuid(12),
                name: label("Normandy"),
                lngLat: [0, 49],
                geometryKind: "area",
            }),
        };
        const events = [
            carrying("m", 20),
            carrying("m", 21, uuid(12)),
            mapEvent({
                id: "other-document",
                document: { id: uuid(2), name: label("Ms 60") },
                place: uuid(12),
                materials: [material("m")],
            }),
            mapEvent({ id: "plain", place: uuid(11) }),
        ];
        const [map] = byMaterial(events, regional, ["m"], none);
        expect([map.places, map.documents, map.components]).toEqual([2, 2, 2]);
        const dots = Object.fromEntries(map.dots.map((d) => [d.id, d]));
        expect(dots[uuid(12)].dashed).toBe(true);
        expect(dots[uuid(10)].dashed).toBe(false);
    });

    it("frames the snapshot so that a place falls on the same spot as its dot", () => {
        const bounds = { west: -2, south: 43, east: 6, north: 51 };
        const shown = fitAspect(
            { west: -4, south: 43, east: 8, north: 51 },
            MINI_WIDTH,
            MINI_HEIGHT,
        );
        const frame = snapshotFrame({ url: "data:", bounds: shown }, bounds);
        const paris = [2.35, 48.85] as const;
        const [dotX, dotY] = project(paris, bounds, MINI_WIDTH, MINI_HEIGHT);
        const [inX, inY] = project(paris, shown, frame.width, frame.height);
        expect(frame.x + inX).toBeCloseTo(dotX, 6);
        expect(frame.y + inY).toBeCloseTo(dotY, 6);
    });

    it("frames a snapshot taken at another size the same way, in that size's box", () => {
        const bounds = { west: -2, south: 43, east: 6, north: 51 };
        const [width, height] = [900, 520];
        const shown = fitAspect(bounds, width, height);
        const frame = snapshotFrame(
            { url: "data:", bounds: shown },
            bounds,
            width,
            height,
        );
        expect(frame.x).toBeCloseTo(0, 6);
        expect(frame.y).toBeCloseTo(0, 6);
        expect(frame.width).toBeCloseTo(width, 6);
        expect(frame.height).toBeCloseTo(height, 6);
        const paris = [2.35, 48.85] as const;
        const [dotX, dotY] = project(paris, bounds, width, height);
        const [inX, inY] = project(paris, shown, frame.width, frame.height);
        expect(frame.x + inX).toBeCloseTo(dotX, 6);
        expect(frame.y + inY).toBeCloseTo(dotY, 6);
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
        ]);
        expect(maps[1].dots[0].slots).toEqual([2]);
    });

    it("lists the centuries of a range", () => {
        expect(centuriesIn([1250, 1420])).toEqual([12, 13, 14]);
    });
});
