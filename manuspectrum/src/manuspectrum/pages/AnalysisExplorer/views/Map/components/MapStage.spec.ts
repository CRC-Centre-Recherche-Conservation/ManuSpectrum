import { flushPromises, mount } from "@vue/test-utils";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import MapStage from "@/manuspectrum/pages/AnalysisExplorer/views/Map/components/MapStage.vue";

import {
    FakeMap,
    SNAPSHOT_URL,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/maplibre.ts";
import {
    BASE_SOURCE,
    OPENFREEMAP_TILES,
    WATER_LAYER,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/base-style.ts";
import { FALLBACK_COLOURS } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-colours.ts";
import {
    BORDERS_LAYER,
    BORDERS_MIN_ZOOM,
    OHM_SOURCE,
    PLACES_SOURCE,
    TERRITORIES_SOURCE,
    bordersFilter,
    territoryOpacity,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Map/stage-layers.ts";

import type { FeatureCollection, Point } from "geojson";
import type { VueWrapper } from "@vue/test-utils";
import type { MapColours } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/map-colours.ts";
import type { PlaceProperties } from "@/manuspectrum/pages/AnalysisExplorer/views/Map/place-symbols.ts";

vi.mock("maplibre-gl", async () =>
    (
        await import(
            "@/manuspectrum/pages/AnalysisExplorer/testing/maplibre.ts"
        )
    ).maplibreModule(),
);

type States = Map<string, Record<string, number | boolean>>;

function place(id: string, lng: number): PlaceProperties & { lng: number } {
    return {
        id,
        kind: "point",
        ring: 10,
        dashed: false,
        name: id,
        documents: 1,
        components: 0,
        pipAway: null,
        lng,
    };
}

function placesOf(...ids: string[]): FeatureCollection<Point, PlaceProperties> {
    return {
        type: "FeatureCollection",
        features: ids.map((id, index) => {
            const { lng, ...properties } = place(id, index);
            return {
                type: "Feature",
                id,
                geometry: { type: "Point", coordinates: [lng, 47] },
                properties,
            };
        }),
    };
}

function statesOf(
    entries: Record<string, Partial<Record<string, number | boolean>>>,
): States {
    return new Map(
        Object.entries(entries).map(([id, state]) => [
            id,
            { t1: 0, t2: 0, t3: 0, t4: 0, dim: false, ...state },
        ]),
    );
}

const BOUNDS = { west: -5, south: 42, east: 8, north: 51 };

function mountStage(
    overrides: Record<string, unknown> = {},
): VueWrapper<InstanceType<typeof MapStage>> {
    return mount(MapStage, {
        props: {
            places: placesOf("paris", "rouen"),
            states: statesOf({ paris: {}, rouen: {} }),
            territories: null,
            colours: FALLBACK_COLOURS,
            borders: false,
            bordersYear: null,
            fit: BOUNDS,
            selected: null,
            ...overrides,
        },
        attachTo: document.body,
    });
}

beforeEach(() => {
    FakeMap.reset();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
});

afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
});

describe("MapStage on load", () => {
    it("fills the places source and puts the territories under the sea", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const map = FakeMap.last();
        expect(map.getSource(PLACES_SOURCE)?.data).toEqual(
            placesOf("paris", "rouen"),
        );
        expect(map.getSource(PLACES_SOURCE)?.spec.promoteId).toBe("id");
        const territories = map.layers.filter(
            (entry) => entry.layer.source === TERRITORIES_SOURCE,
        );
        expect(territories.map((entry) => entry.layer.id)).toEqual([
            "territory-cells",
            "territory-hatch",
            "territory-casing",
            "territory-edges",
        ]);
        expect(territories.every((entry) => entry.before === WATER_LAYER)).toBe(
            true,
        );
        expect(map.getSource(TERRITORIES_SOURCE)?.data).toEqual({
            type: "FeatureCollection",
            features: [],
        });
        wrapper.unmount();
    });

    it("draws every image the layers name before adding them", async () => {
        mountStage();
        await flushPromises();
        const map = FakeMap.last();
        for (const name of [
            "ring-dashed",
            "hatch",
            "pip-firm-1",
            "pip-pale-4",
        ]) {
            expect(map.hasImage(name)).toBe(true);
        }
    });

    it("fits the given bounds at once and mounts no navigation control", async () => {
        mountStage();
        await flushPromises();
        const map = FakeMap.last();
        expect(map.fitCalls[0]).toEqual([
            [
                [-5, 42],
                [8, 51],
            ],
            { padding: 40, duration: 0 },
        ]);
        expect(map.controls).toEqual([]);
        expect(map.options.attributionControl).toEqual({ compact: true });
        expect(map.options.locale).toMatchObject({
            "Map.Title": "Map of the places of the kept events",
        });
    });

    it("hides the historical borders until asked", async () => {
        mountStage();
        await flushPromises();
        const borders = FakeMap.last().getLayer(BORDERS_LAYER);
        expect(borders?.layout).toEqual({ visibility: "none" });
    });

    it("sends the initial feature-states, the selected place included", async () => {
        mountStage({ selected: "rouen" });
        await flushPromises();
        expect(FakeMap.last().featureStates).toEqual([
            [
                { source: PLACES_SOURCE, id: "paris" },
                {
                    t1: 0,
                    t2: 0,
                    t3: 0,
                    t4: 0,
                    dim: false,
                    selected: false,
                },
            ],
            [
                { source: PLACES_SOURCE, id: "rouen" },
                {
                    t1: 0,
                    t2: 0,
                    t3: 0,
                    t4: 0,
                    dim: false,
                    selected: true,
                },
            ],
        ]);
    });
});

describe("MapStage updates", () => {
    it("sends feature-state for the changed places only and never replaces the places data", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const map = FakeMap.last();
        map.featureStates = [];
        await wrapper.setProps({
            states: statesOf({ paris: { t1: 1 }, rouen: {} }),
        });
        expect(map.featureStates).toEqual([
            [
                { source: PLACES_SOURCE, id: "paris" },
                {
                    t1: 1,
                    t2: 0,
                    t3: 0,
                    t4: 0,
                    dim: false,
                    selected: false,
                },
            ],
        ]);
        await wrapper.setProps({ selected: "rouen" });
        expect(map.featureStates.at(-1)?.[0]).toEqual({
            source: PLACES_SOURCE,
            id: "rouen",
        });
        expect(map.featureStates).toHaveLength(2);
        expect(map.getSource(PLACES_SOURCE)?.setDataCalls).toEqual([]);
    });

    it("drops the state of a place that left the states", async () => {
        const wrapper = mountStage();
        await flushPromises();
        await wrapper.setProps({ states: statesOf({ paris: {} }) });
        expect(FakeMap.last().removedStates).toEqual([
            { source: PLACES_SOURCE, id: "rouen" },
        ]);
    });

    it("replaces the places data once when the places change", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const next = placesOf("paris");
        await wrapper.setProps({ places: next });
        expect(FakeMap.last().getSource(PLACES_SOURCE)?.setDataCalls).toEqual([
            next,
        ]);
    });

    it("replaces the territories data, an absent grid by an empty one", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const grid: FeatureCollection = {
            type: "FeatureCollection",
            features: [],
        };
        await wrapper.setProps({ territories: grid });
        await wrapper.setProps({ territories: null });
        expect(
            FakeMap.last().getSource(TERRITORIES_SOURCE)?.setDataCalls,
        ).toEqual([grid, { type: "FeatureCollection", features: [] }]);
    });

    it("toggles the borders and filters them by year", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const map = FakeMap.last();
        await wrapper.setProps({ borders: true });
        await wrapper.setProps({ bordersYear: 1350 });
        expect(map.layoutCalls).toEqual([
            [BORDERS_LAYER, "visibility", "visible"],
        ]);
        expect(map.filterCalls).toEqual([[BORDERS_LAYER, bordersFilter(1350)]]);
    });

    it("repaints only what a colour change touches", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const map = FakeMap.last();
        const colours: MapColours = { ...FALLBACK_COLOURS, sea: "#000001" };
        await wrapper.setProps({ colours });
        expect(map.paintCalls).toEqual([
            [WATER_LAYER, "fill-color", "#000001"],
        ]);
        expect(map.updatedImages).toContain("pip-firm-1");
    });

    it("isolates a slot's territory by paint and restores it, never by data", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const map = FakeMap.last();
        await wrapper.setProps({ isolate: 2 });
        const two = territoryOpacity(2);
        expect(map.paintCalls).toEqual([
            ["territory-cells", "fill-opacity", two.cells],
            ["territory-hatch", "fill-opacity", two.hatch],
            ["territory-casing", "line-opacity", two.casing],
            ["territory-edges", "line-opacity", two.edges],
        ]);
        await wrapper.setProps({ isolate: null });
        const plain = territoryOpacity(null);
        expect(map.paintCalls.slice(4)).toEqual([
            ["territory-cells", "fill-opacity", plain.cells],
            ["territory-hatch", "fill-opacity", plain.hatch],
            ["territory-casing", "line-opacity", plain.casing],
            ["territory-edges", "line-opacity", plain.edges],
        ]);
        expect(map.getSource(TERRITORIES_SOURCE)?.setDataCalls).toEqual([]);
    });

    it("folds the attribution MapLibre opens on its own, once", async () => {
        const wrapper = mountStage();
        const attribution = document.createElement("details");
        attribution.className =
            "maplibregl-ctrl maplibregl-ctrl-attrib maplibregl-compact maplibregl-compact-show";
        wrapper.get(".canvas").element.appendChild(attribution);
        await flushPromises();
        const map = FakeMap.last();
        expect(attribution.classList.contains("maplibregl-compact-show")).toBe(
            false,
        );
        attribution.classList.add("maplibregl-compact-show");
        map.fire("resize");
        expect(attribution.classList.contains("maplibregl-compact-show")).toBe(
            true,
        );
        expect(map.listenerCount("sourcedata")).toBe(0);
    });

    it("waits for the load before touching the map", async () => {
        const wrapper = mountStage();
        await wrapper.setProps({ borders: true });
        const map = FakeMap.last();
        expect(map.layoutCalls).toEqual([]);
        await flushPromises();
        expect(map.getLayer(BORDERS_LAYER)?.layout).toEqual({
            visibility: "visible",
        });
    });
});

describe("MapStage pointer", () => {
    it("emits select for the place under a click", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const map = FakeMap.last();
        map.rendered = [{ properties: { id: "paris" } }];
        map.fire("click", { point: { x: 10, y: 20 } }, "place-points");
        expect(wrapper.emitted("select")).toEqual([["paris"]]);
        map.rendered = [];
        map.fire("click", { point: { x: 1, y: 2 } });
        expect(wrapper.emitted("select")).toHaveLength(1);
    });

    it("marks the hovered place, emits its position, and clears on leave", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const map = FakeMap.last();
        map.featureStates = [];
        map.rendered = [{ properties: { id: "rouen" } }];
        map.fire("mousemove", { point: { x: 30, y: 40 } });
        expect(map.featureStates).toEqual([
            [{ source: PLACES_SOURCE, id: "rouen" }, { hover: true }],
        ]);
        expect(map.canvas.style.cursor).toBe("pointer");
        map.fire("mouseout");
        expect(map.featureStates.at(-1)).toEqual([
            { source: PLACES_SOURCE, id: "rouen" },
            { hover: false },
        ]);
        expect(map.canvas.style.cursor).toBe("");
        expect(wrapper.emitted("hover")).toEqual([
            [{ id: "rouen", x: 30, y: 40 }],
            [null],
        ]);
    });

    it("keeps the pointer's hover when the parent's state of that place changes", async () => {
        const wrapper = mountStage({
            states: statesOf({ paris: { hover: false }, rouen: {} }),
        });
        await flushPromises();
        const map = FakeMap.last();
        map.rendered = [{ properties: { id: "paris" } }];
        map.fire("mousemove", { point: { x: 30, y: 40 } });
        await wrapper.setProps({
            states: statesOf({ paris: { hover: false, t1: 1 }, rouen: {} }),
        });
        expect(map.featureStates.at(-1)).toEqual([
            { source: PLACES_SOURCE, id: "paris" },
            {
                t1: 1,
                t2: 0,
                t3: 0,
                t4: 0,
                dim: false,
                hover: true,
                selected: false,
            },
        ]);
    });

    it("zooms and fits the whole map from its own controls", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const map = FakeMap.last();
        const buttons = wrapper.findAll(".control");
        expect(
            buttons.map((button) => button.attributes("aria-label")),
        ).toEqual(["Zoom in", "Zoom out", "Whole map"]);
        await buttons[0].trigger("click");
        await buttons[1].trigger("click");
        await buttons[2].trigger("click");
        expect(map.zoomCalls.map(([direction]) => direction)).toEqual([
            "in",
            "out",
        ]);
        expect(map.fitCalls).toHaveLength(2);
    });
});

describe("MapStage failures", () => {
    it("emits failed and says so when the map cannot start", async () => {
        FakeMap.failing = true;
        const error = vi.spyOn(console, "error").mockImplementation(() => {});
        const wrapper = mountStage();
        await flushPromises();
        expect(wrapper.emitted("failed")).toEqual([[]]);
        expect(wrapper.find(".unavailable [role='status']").text()).toBe(
            "Map unavailable in this browser: the place list and the timeline still work.",
        );
        expect(error).toHaveBeenCalled();
        error.mockRestore();
    });

    it("offers a retry when the background tiles fail, and keeps the places", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const map = FakeMap.last();
        map.fire("error", { sourceId: "ohm" });
        await flushPromises();
        expect(wrapper.find(".base-failed").exists()).toBe(false);
        map.fire("error", { sourceId: BASE_SOURCE });
        await flushPromises();
        expect(wrapper.find(".base-failed").text()).toContain(
            "Background map unavailable (tile server).",
        );
        map.addSource(BASE_SOURCE, {});
        await wrapper.find(".base-failed .retry").trigger("click");
        expect(map.getSource(BASE_SOURCE)?.urls).toEqual([OPENFREEMAP_TILES]);
        expect(wrapper.find(".base-failed").exists()).toBe(false);
        expect(map.getSource(PLACES_SOURCE)).toBeDefined();
    });
});

describe("MapStage exposed", () => {
    it("snapshots the bare map in the bounds, with the bounds it shows, and puts the camera back", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const map = FakeMap.last();
        map.shown = [
            [-1, 40],
            [11, 50],
        ];
        const shot = wrapper.vm.snapshot({
            west: 0,
            south: 40,
            east: 10,
            north: 50,
        });
        expect(map.fitCalls.at(-1)).toEqual([
            [
                [0, 40],
                [10, 50],
            ],
            { padding: 0, duration: 0 },
        ]);
        const hidden = map.layoutCalls.filter(
            ([, , value]) => value === "none",
        );
        expect(hidden.map(([id]) => id)).toEqual(
            expect.arrayContaining([
                "territory-cells",
                "place-rings",
                "place-labels",
                "pip-1-firm",
            ]),
        );
        expect(hidden.map(([id]) => id)).not.toContain(BORDERS_LAYER);
        map.fire("idle");
        await expect(shot).resolves.toEqual({
            url: SNAPSHOT_URL,
            bounds: { west: -1, south: 40, east: 11, north: 50 },
        });
        expect(map.jumpCalls).toEqual([
            { center: { lng: 2.5, lat: 47 }, zoom: 4, bearing: 0, pitch: 0 },
        ]);
        const shownAgain = map.layoutCalls
            .slice(hidden.length)
            .filter(([, , value]) => value === "visible")
            .map(([id]) => id);
        expect(shownAgain.sort()).toEqual(hidden.map(([id]) => id).sort());
    });

    it("runs one snapshot at a time: a newer request replaces the waiting one, the camera is saved once", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const map = FakeMap.last();
        const first = wrapper.vm.snapshot({
            west: 0,
            south: 40,
            east: 10,
            north: 50,
        });
        const dropped = wrapper.vm.snapshot({
            west: 1,
            south: 41,
            east: 9,
            north: 49,
        });
        const last = wrapper.vm.snapshot({
            west: 2,
            south: 42,
            east: 8,
            north: 48,
        });
        await expect(dropped).resolves.toBeNull();
        expect(map.fitCalls).toHaveLength(2);
        map.fire("idle");
        await expect(first).resolves.toMatchObject({ url: SNAPSHOT_URL });
        expect(map.jumpCalls).toEqual([]);
        expect(map.fitCalls.at(-1)?.[0]).toEqual([
            [2, 42],
            [8, 48],
        ]);
        map.fire("idle");
        await expect(last).resolves.toMatchObject({
            bounds: { west: 2, south: 42, east: 8, north: 48 },
        });
        expect(map.jumpCalls).toEqual([
            { center: { lng: 2.5, lat: 47 }, zoom: 4, bearing: 0, pitch: 0 },
        ]);
    });

    it("takes a snapshot asked before the load once the map has loaded", async () => {
        const wrapper = mountStage();
        const shot = wrapper.vm.snapshot(BOUNDS);
        await flushPromises();
        const map = FakeMap.last();
        expect(map.fitCalls.at(-1)?.[1]).toEqual({ padding: 0, duration: 0 });
        map.fire("idle");
        await expect(shot).resolves.toMatchObject({ url: SNAPSHOT_URL });
    });

    it("eases to a place picked off screen, and stays put for one in view", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const map = FakeMap.last();
        map.shown = [
            [-5, 42],
            [8, 51],
        ];
        wrapper.vm.revealPlace([2.35, 48.85]);
        expect(map.easeCalls).toEqual([]);
        wrapper.vm.revealPlace([-4.02, 39.86]);
        expect(map.easeCalls).toEqual([
            { center: [-4.02, 39.86], duration: 420 },
        ]);
    });

    it("reports its zoom on load and after each move, and loads the borders from their zoom", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const map = FakeMap.last();
        map.fire("moveend");
        expect(wrapper.emitted("zoom")).toEqual([[4], [4]]);
        expect(map.getSource(OHM_SOURCE)?.spec.minzoom).toBe(BORDERS_MIN_ZOOM);
        wrapper.vm.zoomTo(BORDERS_MIN_ZOOM);
        expect(map.easeCalls).toEqual([{ zoom: 7, duration: 420 }]);
    });

    it("snapshots nothing when the map could not start", async () => {
        FakeMap.failing = true;
        const error = vi.spyOn(console, "error").mockImplementation(() => {});
        const wrapper = mountStage();
        await flushPromises();
        await expect(wrapper.vm.snapshot(BOUNDS)).resolves.toBeNull();
        error.mockRestore();
    });

    it("resizes the map on request", async () => {
        const wrapper = mountStage();
        await flushPromises();
        wrapper.vm.resize();
        expect(FakeMap.last().resizeCount).toBe(1);
    });

    it("removes the map when unmounted", async () => {
        const wrapper = mountStage();
        await flushPromises();
        const map = FakeMap.last();
        wrapper.unmount();
        expect(map.removed).toBe(true);
    });
});
