import L from "leaflet";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
    createScaleGroup,
    layServed,
    OVERZOOM_LEVELS,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import {
    fitView,
    fitZoomOf,
    keepsFit,
} from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-sync.ts";

import type { ScaleGroup } from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import type { SyncTarget } from "@/manuspectrum/pages/AnalysisExplorer/views/Compare/pane-sync.ts";

/** The real leaflet-iiif 3.0.0 on a fake image server: only the info.json is answered. */
const SIZES: Record<string, { width: number; height: number }> = {
    tiny: { width: 236, height: 235 },
    large: { width: 1529, height: 2405 },
};

let map: L.Map;
let host: HTMLDivElement;
let room = { w: 600, h: 400 };

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

/** A container whose size the spec can change, as a window being resized. */
function resizableContainer(): HTMLDivElement {
    const element = document.createElement("div");
    Object.defineProperty(element, "clientWidth", {
        get: () => room.w,
    });
    Object.defineProperty(element, "clientHeight", {
        get: () => room.h,
    });
    document.body.append(element);
    return element;
}

function resize(w: number, h: number): void {
    room = { w, h };
    map.invalidateSize({ animate: false });
}

interface Laid {
    target: SyncTarget;
    layer: L.TileLayer;
}

async function lay(name: string, scale?: ScaleGroup): Promise<Laid> {
    let size = { w: 0, h: 0 };
    let nativeZoom = 0;
    const page = layServed(
        map,
        `https://iiif.example/${name}`,
        {
            read: (read, zoom) => {
                size = read;
                nativeZoom = zoom;
            },
            failed: vi.fn(),
        },
        { scale },
    );
    await settle();
    return { target: { map, size, nativeZoom }, layer: page.layer };
}

function imageVisible(target: SyncTarget): boolean {
    const { size, nativeZoom } = target;
    const image = L.latLngBounds(
        map.unproject([0, size.h], nativeZoom),
        map.unproject([size.w, 0], nativeZoom),
    );
    return map.getBounds().intersects(image);
}

beforeEach(() => {
    room = { w: 600, h: 400 };
    vi.stubGlobal(
        "fetch",
        vi.fn((url: string) =>
            Promise.resolve({ json: () => Promise.resolve(infoFor(url)) }),
        ),
    );
    host = resizableContainer();
    map = L.map(host, {
        crs: L.CRS.Simple,
        zoomSnap: 0.25,
        minZoom: -10,
        attributionControl: false,
    }).setView([0, 0], 0);
});

afterEach(() => {
    map.remove();
    host.remove();
    vi.unstubAllGlobals();
});

describe("zoom past the served size (real leaflet-iiif)", () => {
    it("lets the reader zoom OVERZOOM_LEVELS past the native zoom of an image of one tile", async () => {
        const { target, layer } = await lay("tiny");
        expect(target.nativeZoom).toBe(0);
        map.setZoom(20, { animate: false });
        expect(map.getZoom()).toBe(target.nativeZoom + OVERZOOM_LEVELS);
        expect(
            (layer as unknown as { options: { maxNativeZoom: number } }).options
                .maxNativeZoom,
        ).toBe(0);
    });

    it("fills the pane with an image smaller than it", async () => {
        room = { w: 1000, h: 800 };
        map.invalidateSize({ animate: false });
        const { target } = await lay("tiny");
        const fit = fitZoomOf(target) as number;
        fitView(target, fit);
        expect(fit).toBeGreaterThan(0);
        const shown = map.getZoomScale(map.getZoom(), 0) * 235;
        expect(shown).toBeGreaterThan(400);
        expect(keepsFit(target)).toBe(true);
    });

    it("reaches the same maximum after zooming out and back in", async () => {
        const { target } = await lay("tiny");
        fitView(target, fitZoomOf(target) as number);
        map.setZoom(20, { animate: false });
        const first = map.getZoom();
        map.setZoom(first - 3, { animate: false });
        map.setZoom(20, { animate: false });
        expect(map.getZoom()).toBe(first);
        expect(first).toBeGreaterThanOrEqual(
            target.nativeZoom + OVERZOOM_LEVELS,
        );
    });

    it("keeps the limit of a scale group at its pixel zoom plus the over-zoom", async () => {
        const group = createScaleGroup();
        await lay("large", group);
        await lay("tiny", group);
        expect(group.zoom()).toBe(0);
        map.setZoom(20, { animate: false });
        expect(map.getZoom()).toBe(group.zoom() + OVERZOOM_LEVELS);
    });
});

describe("a resized container (real leaflet-iiif)", () => {
    it("keeps the image visible and fitted when the pane grows then shrinks", async () => {
        const { target } = await lay("tiny");
        fitView(target, fitZoomOf(target) as number);
        for (const [w, h] of [
            [1600, 900],
            [1000, 800],
            [120, 90],
            [600, 400],
        ]) {
            const held = keepsFit(target);
            resize(w, h);
            if (held) fitView(target, fitZoomOf(target) as number);
            console.log(
                "STEP",
                w,
                h,
                held,
                map.getZoom(),
                fitZoomOf(target),
                map.getCenter(),
                map.getSize(),
                map.getMaxZoom(),
            );
            expect(imageVisible(target)).toBe(true);
            expect(keepsFit(target)).toBe(true);
            const shown = map.getZoomScale(map.getZoom(), 0) * 235;
            expect(shown).toBeLessThanOrEqual(Math.min(w, h) + 1);
            expect(shown).toBeGreaterThan(Math.min(w, h) * 0.5);
        }
    });

    it("leaves a view the reader moved where it is", async () => {
        const { target } = await lay("tiny");
        fitView(target, fitZoomOf(target) as number);
        map.setZoom(map.getZoom() + 1, { animate: false });
        expect(keepsFit(target)).toBe(false);
        const zoom = map.getZoom();
        resize(900, 500);
        expect(map.getZoom()).toBe(zoom);
        expect(imageVisible(target)).toBe(true);
    });
});
