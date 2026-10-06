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
    huge: { width: 14000, height: 14000 },
    wide: { width: 1378, height: 1355 },
    narrow: { width: 600, height: 677 },
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

/** Where leaflet places the tile `coords` of the layer, in map pixels at the tile zoom (what it writes on the tile element). */
function placedAt(layer: L.TileLayer, x: number, y: number): L.Point {
    const tiles = layer as IiifTiles & {
        _getTilePos: (coords: L.Coords) => L.Point;
        _level: { origin: L.Point };
    };
    const coords = Object.assign(L.point(x, y), {
        z: tiles._tileZoom,
    }) as L.Coords;
    return tiles._getTilePos(coords).add(tiles._level.origin);
}

/** The drawn rectangle of the layer's image, in CRS units: its tile (0, 0) corner and the size its info.json gives at the group's scale. */
function drawnBox(
    layer: L.TileLayer,
    name: string,
): { left: number; top: number; width: number; height: number } {
    const tiles = layer as IiifTiles;
    const factor = 2 ** tiles._tileZoom;
    const origin = placedAt(layer, 0, 0);
    const info = SIZES[name];
    return {
        left: origin.x / factor,
        top: origin.y / factor,
        width: info.width / 2 ** group.zoom(),
        height: info.height / 2 ** group.zoom(),
    };
}

describe("layers of different sizes in one frame (real leaflet-iiif)", () => {
    it("centres the 600×677 layer in the 1378×1355 one, at the same pixel scale", async () => {
        const wide = lay("wide") as IiifTiles;
        const narrow = lay("narrow") as IiifTiles;
        await settle();
        expect(group.frame()).toEqual({ w: 1378, h: 1355 });
        const outer = drawnBox(wide, "wide");
        const inner = drawnBox(narrow, "narrow");
        expect(outer.left).toBe(0);
        expect(outer.top).toBe(0);
        expect(inner.left + inner.width / 2).toBeCloseTo(
            outer.left + outer.width / 2,
            1,
        );
        expect(inner.top + inner.height / 2).toBeCloseTo(
            outer.top + outer.height / 2,
            1,
        );
        expect(inner.width / outer.width).toBeCloseTo(600 / 1378, 6);
        expect(sourcePixelsPerUnit(narrow)).toBeCloseTo(
            sourcePixelsPerUnit(wide),
            6,
        );
    });

    it("puts a layer back at the origin when the larger one leaves, and the same whichever is laid first", async () => {
        const narrow = lay("narrow") as IiifTiles;
        const wide = layServed(
            map,
            "https://iiif.example/wide",
            { read: vi.fn(), failed: vi.fn() },
            { pane: "pane-wide", scale: group },
        );
        await settle();
        expect(drawnBox(narrow, "narrow").left).toBeGreaterThan(0);
        expect(drawnBox(wide.layer, "wide").left).toBe(0);
        wide.remove();
        expect(group.frame()).toEqual({ w: 600, h: 677 });
        expect(drawnBox(narrow, "narrow").left).toBe(0);
        expect(drawnBox(narrow, "narrow").top).toBe(0);
    });

    it("loads the tiles that lie under the screen after the shift, so the smaller layer is not cut at its first column", async () => {
        const narrow = lay("narrow") as IiifTiles;
        lay("wide");
        await settle();
        map.setView(map.unproject([1378 / 2, 1355 / 2], 2), 2, {
            animate: false,
        });
        await settle();
        const keys = Object.values(narrow._tiles).map(
            (tile) => `${tile.coords.x}:${tile.coords.y}`,
        );
        expect(keys).toContain("0:0");
        expect(keys).toContain("0:1");
        expect(Math.max(...keys.map((key) => Number(key.split(":")[0])))).toBe(
            2,
        );
    });
});

describe("a view set as soon as a page is reported read (real leaflet-iiif)", () => {
    it("does not throw in the tile layer: two pages added one after the other", async () => {
        const thrown: unknown[] = [];
        const reads: { w: number; h: number }[] = [];
        for (const name of ["large", "small"]) {
            layServed(
                map,
                `https://iiif.example/${name}`,
                {
                    read: (size) => {
                        reads.push(size);
                        try {
                            map.setView([0, 0], 1, { animate: false });
                        } catch (error) {
                            thrown.push(error);
                        }
                    },
                    failed: vi.fn(),
                },
                { pane: `pane-${name}`, scale: group },
            );
        }
        await settle();
        expect(thrown).toEqual([]);
        expect(reads).toHaveLength(2);
    });

    it("draws tiles at a zoom below the one the layer opens at, once leaflet-iiif has settled its zoom range", async () => {
        map.remove();
        map = L.map(sizedContainer(1200, 200), {
            crs: L.CRS.Simple,
            zoomSnap: 0.25,
            minZoom: -10,
        }).setView([0, 0], 3);
        map.createPane("pane-huge");
        const large = lay("huge") as IiifTiles;
        map.setView([0, 0], -1, { animate: false });
        await settle();
        expect(large.options.minZoom).toBeLessThan(0);
        expect(large._tileZoom).toBe(-1);
        expect(Object.keys(large._tiles).length).toBeGreaterThan(0);
    });

    it("keeps drawing when the pane is later resized so small that the whole image fits below the layer's own range", async () => {
        map.remove();
        map = L.map(sizedContainer(1200, 200), {
            crs: L.CRS.Simple,
            zoomSnap: 0.25,
            minZoom: -10,
        }).setView([0, 0], 3);
        map.createPane("pane-huge");
        const large = lay("huge") as IiifTiles;
        await settle();
        map.setView([0, 0], -4, { animate: false });
        await settle();
        expect(map.getZoom()).toBe(-4);
        expect(Object.keys(large._tiles).length).toBeGreaterThan(0);
    });

    it("asks no tile that lies beyond the image below the zoom range of the image's own levels", async () => {
        map.remove();
        map = L.map(sizedContainer(1200, 200), {
            crs: L.CRS.Simple,
            zoomSnap: 0.25,
            minZoom: -10,
        }).setView([0, 0], 3);
        map.createPane("pane-huge");
        const large = lay("huge") as IiifTiles;
        map.setView([0, 0], -1, { animate: false });
        await settle();
        const regions = Object.values(large._tiles).map((tile) =>
            (large as unknown as { getTileUrl: (c: L.Coords) => string })
                .getTileUrl(tile.coords)
                .split("/")
                .slice(-4)[0]
                .split(",")
                .map(Number),
        );
        expect(regions.length).toBeGreaterThan(0);
        for (const [, , width, height] of regions) {
            expect(width).toBeGreaterThan(0);
            expect(height).toBeGreaterThan(0);
        }
    });

    it("draws the tiles of the view set meanwhile once the container is laid", async () => {
        const large = lay("large") as IiifTiles;
        map.setView([0, 0], 2, { animate: false });
        await settle();
        expect(large._container).toBeDefined();
        expect(large._tileZoom).toBe(2);
        expect(Object.keys(large._tiles).length).toBeGreaterThan(0);
    });
});

describe("createScaleGroup", () => {
    it("tells when joining or leaving moves the common zoom, and not for the first layer", () => {
        const changed = vi.fn();
        const scale = createScaleGroup(changed);
        const apply = vi.fn();
        const large = { nativeZoom: 4, size: { w: 9, h: 9 }, apply };
        const small = { nativeZoom: 3, size: { w: 5, h: 5 }, apply };
        scale.join(large);
        expect(changed).not.toHaveBeenCalled();
        scale.join(small);
        expect(changed).toHaveBeenCalledWith(3);
        expect(apply).toHaveBeenLastCalledWith(3, { x: 2, y: 2 });
        scale.leave(small);
        expect(changed).toHaveBeenLastCalledWith(4);
    });

    it("lays a plain image at the common zoom, whatever the zoom of the others", () => {
        const scale = createScaleGroup();
        const image = {
            nativeZoom: null,
            size: { w: 8, h: 8 },
            apply: vi.fn(),
        };
        scale.join(image);
        expect(image.apply).toHaveBeenLastCalledWith(0, { x: 0, y: 0 });
        scale.join({ nativeZoom: 3, size: { w: 8, h: 8 }, apply: vi.fn() });
        expect(image.apply).toHaveBeenLastCalledWith(3, { x: 0, y: 0 });
    });

    it("centres each member in the box of the widest and the tallest, and tells when the box moves", () => {
        const changed = vi.fn();
        const scale = createScaleGroup(changed);
        const wide = { nativeZoom: 3, size: { w: 100, h: 40 }, apply: vi.fn() };
        const tall = { nativeZoom: 3, size: { w: 60, h: 80 }, apply: vi.fn() };
        scale.join(wide);
        expect(scale.frame()).toEqual({ w: 100, h: 40 });
        scale.join(tall);
        expect(scale.frame()).toEqual({ w: 100, h: 80 });
        expect(changed).toHaveBeenLastCalledWith(3);
        expect(wide.apply).toHaveBeenLastCalledWith(3, { x: 0, y: 20 });
        expect(tall.apply).toHaveBeenLastCalledWith(3, { x: 20, y: 0 });
        scale.leave(tall);
        expect(scale.frame()).toEqual({ w: 100, h: 40 });
        expect(wide.apply).toHaveBeenLastCalledWith(3, { x: 0, y: 0 });
        scale.leave(wide);
        expect(scale.frame()).toBeNull();
    });
});
