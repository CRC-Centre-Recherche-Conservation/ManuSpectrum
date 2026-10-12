import { describe, expect, it } from "vitest";

import {
    absentTracked,
    panelContent,
    subjectEvents,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/panel-groups.ts";
import {
    label,
    mapEvent,
    mapPlace,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

const places = {
    [uuid(10)]: mapPlace(),
    [uuid(12)]: mapPlace({ id: uuid(12), lngLat: null }),
};

function doc(n: number, name: string) {
    return { id: uuid(n), name: label(name) };
}

describe("panel groups", () => {
    it("groups by folded document name, own events first, then components, by type then start", () => {
        const comp = (n: number, name: string) => ({
            id: uuid(n),
            name: label(name),
        });
        const content = panelContent([
            mapEvent({
                id: "b-comp-2",
                document: doc(2, "Éa"),
                component: comp(21, "Zeta"),
                type: "alteration",
                analyses: [uuid(102)],
            }),
            mapEvent({
                id: "b-own-mod",
                document: doc(2, "Éa"),
                type: "modification",
                date: { start: 1500, end: 1500, approximate: false },
                analyses: [uuid(103)],
            }),
            mapEvent({
                id: "b-own-prod",
                document: doc(2, "Éa"),
                type: "production",
                analyses: [uuid(100)],
            }),
            mapEvent({
                id: "b-comp-1",
                document: doc(2, "Éa"),
                component: comp(20, "alpha"),
                type: "production",
                analyses: [uuid(100), uuid(104)],
            }),
            mapEvent({
                id: "a-own",
                document: doc(1, "Eb"),
                analyses: [uuid(105)],
            }),
        ]);
        expect(content.documents.map((d) => d.name.value)).toEqual([
            "Éa",
            "Eb",
        ]);
        const [first] = content.documents;
        expect(first.own.map((e) => e.id)).toEqual(["b-own-prod", "b-own-mod"]);
        expect(first.components.map((c) => c.name.value)).toEqual([
            "alpha",
            "Zeta",
        ]);
        expect(content.components).toBe(2);
        expect(content.analyses).toEqual([
            uuid(100),
            uuid(103),
            uuid(104),
            uuid(102),
            uuid(105),
        ]);
    });

    it("selects the events of a place, a period, a document, a material and the unplaced", () => {
        const m = {
            id: "m",
            name: label("m"),
            reliability: null,
            characterization: uuid(500),
        };
        const events = [
            mapEvent({ id: "paris" }),
            mapEvent({
                id: "old",
                date: { start: 1000, end: 1100, approximate: false },
            }),
            mapEvent({
                id: "undated",
                date: { start: null, end: null, approximate: false },
            }),
            mapEvent({ id: "doc2", document: doc(2, "B"), materials: [m] }),
            mapEvent({ id: "none", place: null }),
            mapEvent({ id: "nocoord", place: uuid(12) }),
        ];
        const ids = (subject: Parameters<typeof subjectEvents>[2]) =>
            subjectEvents(events, places, subject).map((e) => e.id);
        expect(ids({ kind: "place", id: uuid(10) })).toEqual([
            "paris",
            "old",
            "undated",
            "doc2",
        ]);
        expect(ids({ kind: "period", from: 1050, to: 1060 })).toEqual(["old"]);
        expect(ids({ kind: "document", id: uuid(2) })).toEqual(["doc2"]);
        expect(ids({ kind: "material", uri: "m" })).toEqual(["doc2"]);
        expect(ids({ kind: "unplaced" })).toEqual(["none", "nocoord"]);
    });

    it("lists the followed uris no event carries", () => {
        const m = {
            id: "m",
            name: label("m"),
            reliability: null,
            characterization: uuid(500),
        };
        const tracked = [
            { uri: "m", slot: 1 },
            { uri: "x", slot: 2 },
        ];
        expect(absentTracked([mapEvent({ materials: [m] })], tracked)).toEqual([
            { uri: "x", slot: 2 },
        ]);
    });
});
