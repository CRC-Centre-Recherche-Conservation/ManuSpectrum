import L from "leaflet";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
    createScaleGroup,
    layServed,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import { sizedContainer } from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";

import type { ScaleGroup } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";

/** The real leaflet-iiif 3.0.0 on a fake image server: only the info.json is answered. */
const SIZES: Record<string, { width: number; height: number }> = {
    small: { width: 600, height: 1202 },
    large: { width: 1529, height: 2405 },
    same: { width: 700, height: 1300 },
};

type IiifTiles = L.TileLayer & {
    _tileZoom: number;
    _tiles: Record<string, { coords: L.Coords; current: boolean }>;
    _container?: HTMLElement;
    maxNativeZoom: number;
    _tileCoordsToNwSe: (coords: L.Coords) => L.LatLng[];
};

let map: L.Map;
let group: ScaleGroup;

function infoFor(url: string): object {
    const key = Object.keys(SIZES).find((name) => url.includes(`/${name}/`));
    return {
        "@context": "http://iiif.io/api/image/2/context.json",
        profile: ["http://iiif.io/api/image/2/level1.json"],
        ...SIZES[key as string],
    };
}

async function settle(): Promise<void> {
    for (let turn = 0; turn < 8; turn += 1) await Promise.resolve();
}

function lay(name: string, scale: ScaleGroup | null = group): L.TileLayer {
    const page = layServed(
        map,
        `https://iiif.example/${name}`,
        { read: vi.fn(), failed: vi.fn() },
        { pane: `pane-${name}`, scale: scale ?? undefined },
    );
    return page.layer;
}

/** Source pixels one CRS unit of the layer stands for, read off its tile (1, 0): where its region starts against where it is placed. */
function sourcePixelsPerUnit(layer: L.TileLayer): number {
    const tiles = layer as IiifTiles;
    const coords = Object.assign(L.point(1, 0), {
        z: tiles._tileZoom,
    }) as L.Coords;
    const url = (
        layer as unknown as { getTileUrl: (c: L.Coords) => string }
    ).getTileUrl(coords);
    const region = url.split("/")[url.split("/").length - 4];
    const start = Number(region.split(",")[0]);
    const placedAt = tiles._tileCoordsToNwSe(coords)[0].lng;
    return start / placedAt;
}

beforeEach(() => {
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string) =>
            Promise.resolve({ json: () => Promise.resolve(infoFor(url)) }),
        ),
    );
    map = L.map(sizedContainer(800, 600), {
        crs: L.CRS.Simple,
        zoomSnap: 0.25,
        minZoom: -10,
    }).setView([0, 0], 3);
    for (const name of Object.keys(SIZES)) map.createPane(`pane-${name}`);
    group = createScaleGroup();
});

afterEach(() => {
    map.remove();
    vi.unstubAllGlobals();
});

describe("layers of different power-of-two buckets in one map (real leaflet-iiif)", () => {
    it("shows the defect of leaflet-iiif 3.0.0 when no group is given: a factor of two between the buckets", async () => {
        const small = lay("small", null);
        const large = lay("large", null);
        await settle();
        expect(sourcePixelsPerUnit(large)).toBe(2 * sourcePixelsPerUnit(small));
    });

    it("draws 600×1202 and 1529×2405 with the same source pixels per unit", async () => {
        const small = lay("small") as IiifTiles;
        const large = lay("large") as IiifTiles;
        await settle();
        expect(map.hasLayer(small)).toBe(true);
        expect(map.hasLayer(large)).toBe(true);
        expect([small.maxNativeZoom, large.maxNativeZoom]).toEqual([3, 4]);
        expect(group.zoom()).toBe(3);
        expect(sourcePixelsPerUnit(small)).toBeCloseTo(
            sourcePixelsPerUnit(large),
            6,
        );
        expect(sourcePixelsPerUnit(small)).toBe(2 ** 3);
    });

    it("gives the same result whichever layer is laid first", async () => {
        const large = lay("large");
        const small = lay("small");
        await settle();
        expect(sourcePixelsPerUnit(small)).toBeCloseTo(
            sourcePixelsPerUnit(large),
            6,
        );
        expect(group.zoom()).toBe(3);
    });

    it("keeps the pixel ratio of two layers when one joins after the other drew its tiles", async () => {
        const large = lay("large") as IiifTiles;
        await settle();
        expect(large._container).toBeDefined();
        expect(sourcePixelsPerUnit(large)).toBe(2 ** 4);
        const small = lay("small");
        await settle();
        expect(sourcePixelsPerUnit(large)).toBe(2 ** 3);
        expect(sourcePixelsPerUnit(small)).toBe(2 ** 3);
    });

    it("recomputes the tile zoom of a layer already drawn when a smaller one joins, one zoom below the map's", async () => {
        map.setView([0, 0], 4);
        const large = lay("large") as IiifTiles;
        await settle();
        const before = Object.values(large._tiles);
        expect(before.length).toBeGreaterThan(0);
        expect(large._tileZoom).toBe(4);
        lay("small");
        await settle();
        expect(large.options.maxNativeZoom).toBe(3);
        expect(large._tileZoom).toBe(3);
        const current = Object.values(large._tiles).filter(
            (tile) => tile.current,
        );
        expect(current.length).toBeGreaterThan(0);
        for (const tile of current) expect(tile.coords.z).toBe(3);
    });

    it("leaves a layer alone at its own scale", async () => {
        const large = lay("large") as IiifTiles;
        await settle();
        expect(sourcePixelsPerUnit(large)).toBe(2 ** 4);
        expect(large.options.zoomOffset).toBe(0);
    });

    it("restores the scale of a layer left alone when the smaller one is removed", async () => {
        const large = lay("large") as IiifTiles;
        const small = layServed(
            map,
            "https://iiif.example/small",
            { read: vi.fn(), failed: vi.fn() },
            { pane: "pane-small", scale: group },
        );
        await settle();
        expect(sourcePixelsPerUnit(large)).toBe(2 ** 3);
        small.remove();
        expect(group.zoom()).toBe(4);
        expect(sourcePixelsPerUnit(large)).toBe(2 ** 4);
    });
});

describe("createScaleGroup", () => {
    it("tells when joining or leaving moves the common zoom, and not for the first layer", () => {
        const changed = vi.fn();
        const scale = createScaleGroup(changed);
        const apply = vi.fn();
        const large = { nativeZoom: 4, apply };
        const small = { nativeZoom: 3, apply };
        scale.join(large);
        expect(changed).not.toHaveBeenCalled();
        scale.join(small);
        expect(changed).toHaveBeenCalledWith(3);
        expect(apply).toHaveBeenLastCalledWith(3);
        scale.leave(small);
        expect(changed).toHaveBeenLastCalledWith(4);
    });

    it("lays a plain image at the common zoom, whatever the zoom of the others", () => {
        const scale = createScaleGroup();
        const image = { nativeZoom: null, apply: vi.fn() };
        scale.join(image);
        expect(image.apply).toHaveBeenLastCalledWith(0);
        scale.join({ nativeZoom: 3, apply: vi.fn() });
        expect(image.apply).toHaveBeenLastCalledWith(3);
    });
});
