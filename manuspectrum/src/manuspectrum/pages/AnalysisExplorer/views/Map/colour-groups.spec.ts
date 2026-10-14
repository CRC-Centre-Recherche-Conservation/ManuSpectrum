import { describe, expect, it } from "vitest";

import {
    colourTree,
    materialCounts,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/colour-groups.ts";
import {
    label,
    mapEvent,
    uuid,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/fixtures.ts";

import type {
    EventMaterial,
    MapColour,
    MapMaterial,
} from "@/manuspectrum/pages/AnalysisExplorer/api/types.ts";

function material(id: string, colours: string[] = []): EventMaterial {
    return {
        id,
        name: label(id),
        reliability: null,
        characterization: uuid(500),
        colours,
        matches: true,
        componentColours: [],
    };
}

function known(uri: string, colours: string[]): MapMaterial {
    return { uri, label: label(uri), colours, swatch: null, ancestors: [] };
}

const colours: Record<string, MapColour> = {
    red: { uri: "red", label: label("Red"), swatch: "#c00" },
    blue: { uri: "blue", label: label("Blue"), swatch: "#00c" },
};

const materials = {
    cinnabar: known("cinnabar", ["red", "blue"]),
    minium: known("minium", ["red"]),
    azurite: known("azurite", ["blue"]),
    mystery: known("mystery", []),
};

function event(
    id: string,
    document: number,
    uris: string[],
    component?: number,
) {
    return mapEvent({
        id,
        document: { id: uuid(document), name: label(`d${document}`) },
        component: component ? { id: uuid(component), name: label("c") } : null,
        materials: uris.map((uri) => material(uri)),
    });
}

describe("colour tree", () => {
    const events = [
        event("1", 1, ["cinnabar", "minium"], 20),
        event("2", 2, ["azurite"], 21),
        event("3", 2, ["azurite"], 22),
        event("4", 3, ["mystery"]),
    ];

    it("counts distinct documents and components per material", () => {
        const counts = materialCounts(events);
        expect(counts.get("azurite")).toMatchObject({
            documents: 1,
            components: 2,
        });
        expect(counts.get("mystery")).toMatchObject({
            documents: 1,
            components: 0,
        });
    });

    it("groups by first colour, the group without colour last", () => {
        const tree = colourTree(events, materials, colours);
        expect(tree.map((g) => g.colour)).toEqual(["blue", "red", null]);
        expect(tree[1].rows.map((r) => r.uri)).toEqual(["cinnabar", "minium"]);
        expect(tree[1].rows[0].colours).toEqual(["red", "blue"]);
        expect(tree[1].swatch).toBe("#c00");
        expect(tree[2].label).toBeNull();
    });

    it("counts a document carrying two materials of one group once", () => {
        const red = colourTree(events, materials, colours).find(
            (g) => g.colour === "red",
        );
        expect(red).toMatchObject({ documents: 1, components: 1 });
        expect(red?.rows.map((r) => r.components)).toEqual([1, 1]);
    });

    it("narrows to the given uris and leaves empty groups out", () => {
        const tree = colourTree(
            events,
            materials,
            colours,
            new Set(["minium"]),
        );
        expect(tree.map((g) => g.colour)).toEqual(["red"]);
        expect(tree[0].rows.map((r) => r.uri)).toEqual(["minium"]);
    });

    it("keeps a group without rows for each ticked colour it names", () => {
        const tree = colourTree(
            events,
            materials,
            colours,
            new Set(["minium"]),
            ["blue", "green"],
        );
        expect(tree.map((g) => g.colour)).toEqual(["red", "blue"]);
        expect(tree[1]).toMatchObject({
            label: label("Blue"),
            swatch: "#00c",
            rows: [],
            documents: 0,
            components: 0,
        });
    });

    it("orders groups by components then label, rows by components then label", () => {
        const more = [
            ...events,
            event("5", 4, ["minium"], 23),
            event("6", 5, ["minium"], 24),
        ];
        const tree = colourTree(more, materials, colours);
        expect(tree.map((g) => g.colour)).toEqual(["red", "blue", null]);
        expect(tree[0].rows.map((r) => r.uri)).toEqual(["minium", "cinnabar"]);
    });

    describe("a ticked colour", () => {
        const leadWhite = known("lead-white", ["red", "blue"]);
        const known2 = { ...materials, "lead-white": leadWhite };
        const observed = [
            mapEvent({
                id: "7",
                document: { id: uuid(7), name: label("d7") },
                component: { id: uuid(27), name: label("c") },
                materials: [material("lead-white", ["red"])],
            }),
            mapEvent({
                id: "8",
                document: { id: uuid(8), name: label("d8") },
                component: { id: uuid(28), name: label("c") },
                materials: [material("lead-white", ["red"])],
            }),
            mapEvent({
                id: "9",
                document: { id: uuid(9), name: label("d9") },
                component: { id: uuid(29), name: label("c") },
                materials: [material("lead-white", ["blue"])],
            }),
            mapEvent({
                id: "2",
                document: { id: uuid(2), name: label("d2") },
                component: { id: uuid(21), name: label("c") },
                materials: [material("azurite", ["blue"])],
            }),
            mapEvent({
                id: "3",
                document: { id: uuid(3), name: label("d3") },
                component: { id: uuid(22), name: label("c") },
                materials: [material("azurite", ["green"])],
            }),
        ];

        it("lists a material observed in it under it too, with that colour's counts", () => {
            const tree = colourTree(observed, known2, colours, undefined, [
                "blue",
            ]);
            const blue = tree.find((g) => g.colour === "blue");
            const red = tree.find((g) => g.colour === "red");
            expect(blue?.rows).toEqual([
                expect.objectContaining({
                    uri: "azurite",
                    observedIn: "blue",
                    documents: 1,
                    components: 1,
                }),
                expect.objectContaining({
                    uri: "lead-white",
                    observedIn: "blue",
                    documents: 1,
                    components: 1,
                }),
            ]);
            expect(red?.rows).toEqual([
                expect.objectContaining({
                    uri: "lead-white",
                    observedIn: null,
                    documents: 3,
                    components: 3,
                }),
            ]);
            expect(blue).toMatchObject({ documents: 2, components: 2 });
        });

        it("lists a material reaching it only through its Component, marked so", () => {
            const throughComponent = [
                ...events,
                mapEvent({
                    id: "10",
                    document: { id: uuid(10), name: label("d10") },
                    component: { id: uuid(30), name: label("c") },
                    materials: [
                        { ...material("mystery"), componentColours: ["blue"] },
                    ],
                }),
            ];
            const tree = colourTree(
                throughComponent,
                materials,
                colours,
                undefined,
                ["blue"],
            );
            const blue = tree.find((g) => g.colour === "blue");
            const mystery = blue?.rows.find((row) => row.uri === "mystery");
            expect(mystery).toMatchObject({
                observedIn: "blue",
                viaComponent: true,
                documents: 1,
                components: 1,
            });
            expect(
                blue?.rows.find((row) => row.uri === "azurite")?.viaComponent,
            ).toBe(false);
            expect(blue).toMatchObject({ documents: 2, components: 3 });
            const none = tree.find((g) => g.colour === null);
            expect(none?.rows[0]).toMatchObject({
                uri: "mystery",
                observedIn: null,
                documents: 2,
            });
        });

        it("lists it once when no colour is ticked", () => {
            const rows = colourTree(observed, known2, colours).flatMap((g) =>
                g.rows.map((row) => row.uri),
            );
            expect(rows.filter((uri) => uri === "lead-white")).toHaveLength(1);
        });

        it("lists a material whose main colour it is once, with that colour's counts", () => {
            const tree = colourTree(observed, known2, colours, undefined, [
                "red",
            ]);
            const red = tree.find((g) => g.colour === "red");
            expect(red?.rows).toEqual([
                expect.objectContaining({
                    uri: "lead-white",
                    observedIn: "red",
                    documents: 2,
                    components: 2,
                }),
            ]);
        });

        it("keeps the usual row of a material of its own that no event observes in it", () => {
            const tree = colourTree(
                observed.filter((e) => e.id !== "2"),
                known2,
                colours,
                undefined,
                ["blue"],
            );
            const blue = tree.find((g) => g.colour === "blue");
            expect(blue?.rows[0]).toMatchObject({
                uri: "azurite",
                observedIn: null,
                documents: 1,
            });
        });

        it("keeps the search narrowing", () => {
            const tree = colourTree(
                observed,
                known2,
                colours,
                new Set(["azurite"]),
                ["blue"],
            );
            expect(tree.flatMap((g) => g.rows.map((row) => row.uri))).toEqual([
                "azurite",
            ]);
        });
    });
});
