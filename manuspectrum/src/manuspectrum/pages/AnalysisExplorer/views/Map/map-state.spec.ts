import { describe, expect, it } from "vitest";

import {
    clampRadius,
    clampThreshold,
    DEFAULT_EVENT_TYPES,
    defaultMapState,
    mapStateFromQuery,
    shownEventTypes,
    writeMapState,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-state.ts";

describe("map state in the address", () => {
    it("writes no key for the default state", () => {
        const query = new URLSearchParams();
        writeMapState(defaultMapState(), query);
        expect(query.toString()).toBe("");
    });

    it("reads every key, clamping the radius and keeping the holes of track", () => {
        const state = mapStateFromQuery(
            new URLSearchParams(
                "mode=territories&colour=dominant&radius=1000&threshold=1.3&multiples=century&track=a&track=-&track=b&brush=1300,1400&layers=borders",
            ),
        );
        expect(state).toEqual({
            mode: "territories",
            colour: "dominant",
            radius: 400,
            threshold: 1.25,
            multiples: "century",
            track: ["a", null, "b"],
            brush: [1300, 1400],
            borders: true,
            legend: false,
        });
    });

    it("keeps the legend out of the address, folded by default", () => {
        const query = new URLSearchParams();
        writeMapState({ ...defaultMapState(), legend: true }, query);
        expect(query.toString()).toBe("");
        expect(defaultMapState().legend).toBe(false);
    });

    it("falls back to the defaults on a reversed brush and a bad radius", () => {
        const state = mapStateFromQuery(
            new URLSearchParams(
                "brush=1400,1300&radius=abc&threshold=-1&mode=nope",
            ),
        );
        expect(state).toEqual(defaultMapState());
    });

    it("round-trips", () => {
        const query = new URLSearchParams(
            "mode=multiples&radius=90&threshold=2.5&track=a&track=-&track=b&brush=-100,50&layers=borders",
        );
        const out = new URLSearchParams();
        writeMapState(mapStateFromQuery(query), out);
        expect(mapStateFromQuery(out)).toEqual(mapStateFromQuery(query));
        expect(out.getAll("track")).toEqual(["a", "-", "b"]);
    });

    it("clamps a radius to its bounds", () => {
        expect(clampRadius(10)).toBe(60);
        expect(clampRadius(150.4)).toBe(150);
        expect(clampRadius(Number.NaN)).toBe(150);
    });

    it("keeps a threshold on its quarter steps, within its bounds", () => {
        expect(defaultMapState().threshold).toBe(0.5);
        expect(clampThreshold(0)).toBe(0.25);
        expect(clampThreshold(9)).toBe(3);
        expect(clampThreshold(0.8)).toBe(0.75);
        expect(clampThreshold(Number.NaN)).toBe(0.5);
        const query = new URLSearchParams();
        writeMapState({ ...defaultMapState(), threshold: 1.5 }, query);
        expect(query.toString()).toBe("threshold=1.5");
    });
});

describe("shownEventTypes", () => {
    it("shows the server defaults when none is selected", () => {
        expect(DEFAULT_EVENT_TYPES).toEqual([
            "production",
            "modification",
            "alteration",
        ]);
        expect(shownEventTypes([])).toEqual([...DEFAULT_EVENT_TYPES]);
    });

    it("shows the selection when there is one", () => {
        expect(shownEventTypes(["alteration"])).toEqual(["alteration"]);
    });
});
