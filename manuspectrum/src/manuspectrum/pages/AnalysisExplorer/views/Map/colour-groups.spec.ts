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

function material(id: string): EventMaterial {
    return {
        id,
        name: label(id),
        reliability: null,
        characterization: uuid(500),
    };
}

function known(uri: string, colours: string[]): MapMaterial {
    return { uri, label: label(uri), colours, swatch: null };
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
        materials: uris.map(material),
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
});
