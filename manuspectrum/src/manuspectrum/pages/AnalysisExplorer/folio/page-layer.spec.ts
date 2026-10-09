import L from "leaflet";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
    createScaleGroup,
    fitPage,
    layImage,
    layPage,
    layServed,
    nativeZoomOf,
    pageBoundsOf,
    servedSize,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import { overlayPane } from "@/manuspectrum/pages/AnalysisExplorer/folio/overlays.ts";
import {
    drawnExtent,
    sizedContainer,
} from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";

vi.mock("leaflet-iiif", () => ({}));

type FakePage = L.LayerGroup & {
    _infoPromise?: Promise<unknown>;
    _imageSizes?: unknown[];
    _container?: HTMLElement;
    _fitBounds?: () => void;
};

let map: L.Map;
let answer: { resolve: () => void; reject: (reason: unknown) => void };
let fake: FakePage;
let factory: ReturnType<typeof vi.fn>;

function pendingPage(sizes: unknown[] | undefined): FakePage {
    const layer = L.layerGroup() as FakePage;
    layer._infoPromise = new Promise<void>((resolve, reject) => {
        answer = {
            resolve: () => {
                layer._imageSizes = sizes;
                resolve();
            },
            reject,
        };
    });
    return layer;
}

beforeEach(() => {
    map = L.map(sizedContainer(), { crs: L.CRS.Simple }).setView([0, 0], 0);
    fake = pendingPage([{ x: 10, y: 10 }]);
    factory = vi.fn(() => fake);
    (L.tileLayer as unknown as { iiif: unknown }).iiif = factory;
});

afterEach(() => {
    map.remove();
});

describe("layPage", () => {
    it("asks the info.json of the service and lays the page once it is read", async () => {
        const failed = vi.fn();
        layPage(map, "https://iiif.example/image/p1", failed);
        expect(factory).toHaveBeenCalledWith(
            "https://iiif.example/image/p1/info.json",
            { fitBounds: true, setMaxBounds: false },
        );
        expect(map.hasLayer(fake)).toBe(false);
        answer.resolve();
        await Promise.resolve();
        await Promise.resolve();
        expect(map.hasLayer(fake)).toBe(true);
        expect(failed).not.toHaveBeenCalled();
    });

    it("never lays a page removed before its info.json answers", async () => {
        const failed = vi.fn();
        const page = layPage(map, "https://iiif.example/image/p1", failed);
        page.remove();
        answer.resolve();
        await Promise.resolve();
        await Promise.resolve();
        expect(map.hasLayer(fake)).toBe(false);
        expect(failed).not.toHaveBeenCalled();
    });

    it("says the page failed when its info.json gives no size, or cannot be read", async () => {
        const failed = vi.fn();
        fake = pendingPage(undefined);
        layPage(map, "https://iiif.example/image/p1", failed);
        answer.resolve();
        await Promise.resolve();
        await Promise.resolve();
        expect(failed).toHaveBeenCalledTimes(1);
        fake = pendingPage([]);
        layPage(map, "https://iiif.example/image/p2", failed, {
            fitBounds: false,
        });
        expect(factory).toHaveBeenLastCalledWith(
            "https://iiif.example/image/p2/info.json",
            { fitBounds: false, setMaxBounds: false },
        );
        answer.reject(new Error("refused"));
        await Promise.resolve();
        await Promise.resolve();
        expect(failed).toHaveBeenCalledTimes(2);
        expect(map.hasLayer(fake)).toBe(false);
    });

    it("says nothing when a page removed before a failed read", async () => {
        const failed = vi.fn();
        layPage(map, "https://iiif.example/image/p1", failed).remove();
        answer.reject(new Error("refused"));
        await Promise.resolve();
        await Promise.resolve();
        expect(failed).not.toHaveBeenCalled();
    });

    it("takes a laid page off the map, its tiles laid or not", async () => {
        const onRemove = vi.spyOn(L.LayerGroup.prototype, "onRemove");
        const page = layPage(map, "https://iiif.example/image/p1", vi.fn());
        answer.resolve();
        await Promise.resolve();
        await Promise.resolve();
        page.remove();
        expect(map.hasLayer(fake)).toBe(false);
        expect(onRemove).not.toHaveBeenCalled();
        fake = pendingPage([{ x: 10, y: 10 }]);
        fake._container = document.createElement("div");
        const laid = layPage(map, "https://iiif.example/image/p2", vi.fn());
        answer.resolve();
        await Promise.resolve();
        await Promise.resolve();
        laid.remove();
        expect(onRemove).toHaveBeenCalledTimes(1);
        onRemove.mockRestore();
    });
});

describe("fitPage", () => {
    it("fits the whole image of a laid page only", async () => {
        fake._fitBounds = vi.fn();
        expect(fitPage(map, null)).toBe(false);
        const page = layPage(map, "https://iiif.example/image/p1", vi.fn());
        expect(fitPage(map, page)).toBe(false);
        answer.resolve();
        await Promise.resolve();
        await Promise.resolve();
        expect(fitPage(map, page)).toBe(true);
        expect(fake._fitBounds).toHaveBeenCalledTimes(1);
    });
});

describe("servedSize", () => {
    it("reads the largest size the info.json gave, never the declared one", async () => {
        fake = pendingPage([
            { x: 300, y: 500 },
            { x: 600, y: 1000 },
            { x: 1529, y: 2405 },
        ]);
        const page = layPage(map, "https://iiif.example/image/p1", vi.fn());
        expect(servedSize(page)).toBeNull();
        answer.resolve();
        await Promise.resolve();
        await Promise.resolve();
        expect(servedSize(page)).toEqual({ w: 1529, h: 2405 });
        expect(nativeZoomOf(page)).toBe(2);
    });

    it("lays the page bounds at size / 2^nativeZoom units, y down", async () => {
        fake = pendingPage([
            { x: 300, y: 500 },
            { x: 1529, y: 2405 },
        ]);
        const page = layPage(map, "https://iiif.example/image/p1", vi.fn());
        expect(pageBoundsOf(page)).toBeNull();
        answer.resolve();
        await Promise.resolve();
        await Promise.resolve();
        expect(pageBoundsOf(page)).toEqual([
            [-2405 / 2, 0],
            [0, 1529 / 2],
        ]);
        expect(pageBoundsOf(null)).toBeNull();
    });

    it("reads no size from a missing page or a size that is not a number", async () => {
        expect(servedSize(null)).toBeNull();
        expect(nativeZoomOf(null)).toBe(0);
        fake = pendingPage([{}]);
        const page = layPage(map, "https://iiif.example/image/p1", vi.fn());
        answer.resolve();
        await Promise.resolve();
        await Promise.resolve();
        expect(servedSize(page)).toBeNull();
    });
});

describe("layPage in a pane", () => {
    it("asks leaflet-iiif for the layer in the given pane, and only then", () => {
        layPage(map, "https://iiif.example/image/p1", vi.fn(), {
            fitBounds: false,
            pane: "stack-a",
        });
        expect(factory).toHaveBeenCalledWith(
            "https://iiif.example/image/p1/info.json",
            { fitBounds: false, setMaxBounds: false, pane: "stack-a" },
        );
    });
});

describe("layServed", () => {
    async function settle(): Promise<void> {
        await Promise.resolve();
        await Promise.resolve();
    }

    it("tells the served size and the native zoom once the page is on the map", async () => {
        const read = vi.fn();
        layServed(map, "https://iiif.example/image/p1", {
            read,
            failed: vi.fn(),
        });
        expect(read).not.toHaveBeenCalled();
        answer.resolve();
        await settle();
        expect(read).toHaveBeenCalledWith({ w: 10, h: 10 }, 0);
    });

    it("fails when the info.json is refused or holds no size", async () => {
        const failed = vi.fn();
        fake = pendingPage([{}]);
        layServed(map, "https://iiif.example/image/p1", {
            read: vi.fn(),
            failed,
        });
        answer.resolve();
        await settle();
        expect(failed).toHaveBeenCalled();
    });

    it("says nothing of a page removed before it was laid", async () => {
        const read = vi.fn();
        const page = layServed(map, "https://iiif.example/image/p1", {
            read,
            failed: vi.fn(),
        });
        page.remove();
        answer.resolve();
        await settle();
        expect(read).not.toHaveBeenCalled();
    });
});

describe("layImage", () => {
    class FakeImage {
        static served: Record<string, { w: number; h: number }> = {};
        static asked: string[] = [];
        onload: (() => void) | null = null;
        onerror: (() => void) | null = null;
        naturalWidth = 0;
        naturalHeight = 0;
        set src(value: string) {
            FakeImage.asked.push(value);
            const size = FakeImage.served[value];
            if (size) {
                this.naturalWidth = size.w;
                this.naturalHeight = size.h;
            }
            queueMicrotask(() => (size ? this.onload : this.onerror)?.());
        }
    }

    const BY_URL = {
        service: null,
        url: "https://img.example/a.png",
        width: 0,
        height: 0,
    };

    async function settle(): Promise<void> {
        for (let turn = 0; turn < 4; turn += 1) await Promise.resolve();
    }

    beforeEach(() => {
        FakeImage.served = { "https://img.example/a.png": { w: 600, h: 1000 } };
        FakeImage.asked = [];
        vi.stubGlobal("Image", FakeImage);
    });

    afterEach(() => {
        vi.unstubAllGlobals();
    });

    it("lays an image given by URL as an overlay at its natural size and says so", async () => {
        const read = vi.fn();
        layImage(map, BY_URL, { read, failed: vi.fn() });
        await settle();
        expect(read).toHaveBeenCalledTimes(1);
        const [size, zoom, layer] = read.mock.calls[0];
        expect(size).toEqual({ w: 600, h: 1000 });
        expect(zoom).toBe(0);
        expect(layer).toBeInstanceOf(L.ImageOverlay);
        expect(map.hasLayer(layer)).toBe(true);
        expect(drawnExtent(layer)).toEqual({ w: 600, h: 1000 });
    });

    it("fails when the image has no address or none answers, and reads one that answers", async () => {
        const image = {
            service: "https://iiif.example/image/p1",
            url: null,
            width: 2000,
            height: 3000,
        };
        FakeImage.served = {};
        const failed = vi.fn();
        const noService = { ...image, service: "" };
        layImage(map, noService, { read: vi.fn(), failed });
        await settle();
        expect(failed).toHaveBeenCalledTimes(1);
        const chained = { ...BY_URL, url: "https://img.example/b.png" };
        const read = vi.fn();
        FakeImage.served = { "https://img.example/b.png": { w: 5, h: 5 } };
        layImage(map, chained, { read, failed });
        await settle();
        expect(read).toHaveBeenCalledTimes(1);
    });

    it("says nothing of an image removed before it was read, and takes a laid one off", async () => {
        const read = vi.fn();
        const early = layImage(map, BY_URL, { read, failed: vi.fn() });
        early.remove();
        await settle();
        expect(read).not.toHaveBeenCalled();
        const laid = layImage(map, BY_URL, { read, failed: vi.fn() });
        await settle();
        const layer = read.mock.calls[0][2];
        laid.remove();
        expect(map.hasLayer(layer)).toBe(false);
    });

    it("lays the overlay in the given pane and has it answer for the divider", async () => {
        const pane = overlayPane(map, "side-a");
        const read = vi.fn();
        layImage(
            map,
            BY_URL,
            { read, failed: vi.fn() },
            { pane, curtain: true },
        );
        await settle();
        const layer = read.mock.calls[0][2] as L.ImageOverlay & {
            getContainer: () => HTMLElement;
        };
        expect(layer.options.pane).toBe(pane);
        expect(layer.getContainer()).toBe(map.getPane(pane));
    });

    it("lays a service image through layServed and passes its layer on", async () => {
        const read = vi.fn();
        layImage(
            map,
            {
                service: "https://iiif.example/image/p1",
                url: null,
                width: 10,
                height: 10,
            },
            { read, failed: vi.fn() },
            { pane: overlayPane(map, "side-b") },
        );
        answer.resolve();
        await settle();
        expect(read).toHaveBeenCalledWith({ w: 10, h: 10 }, 0, fake);
    });

    it("lays an overlay at the common pixel scale of its group and again when the scale moves", async () => {
        const scale = createScaleGroup();
        const read = vi.fn();
        layImage(map, BY_URL, { read, failed: vi.fn() }, { scale });
        await settle();
        const layer = read.mock.calls[0][2] as L.ImageOverlay;
        expect(drawnExtent(layer)).toEqual({ w: 600, h: 1000 });
        scale.join({ nativeZoom: 3, size: { w: 10, h: 10 }, apply: vi.fn() });
        expect(drawnExtent(layer)).toEqual({ w: 75, h: 125 });
    });

    it("centres an overlay in the frame of a larger one at the same pixel scale, never stretched", async () => {
        FakeImage.served = {
            "https://img.example/a.png": { w: 600, h: 1000 },
            "https://img.example/big.png": { w: 1400, h: 1200 },
        };
        const scale = createScaleGroup();
        const read = vi.fn();
        layImage(map, BY_URL, { read, failed: vi.fn() }, { scale });
        layImage(
            map,
            { ...BY_URL, url: "https://img.example/big.png" },
            { read, failed: vi.fn() },
            { scale },
        );
        await settle();
        const [small, big] = read.mock.calls.map(
            (call) => call[2] as L.ImageOverlay,
        );
        expect(scale.frame()).toEqual({ w: 1400, h: 1200 });
        const bounds = (layer: L.ImageOverlay) => {
            const box = layer.getBounds();
            return {
                west: box.getWest(),
                east: box.getEast(),
                north: box.getNorth(),
                south: box.getSouth(),
            };
        };
        const outer = bounds(big);
        const inner = bounds(small);
        expect(outer.west).toBe(0);
        expect(outer.north).toBeCloseTo(0, 9);
        expect((inner.west + inner.east) / 2).toBeCloseTo(
            (outer.west + outer.east) / 2,
            6,
        );
        expect((inner.north + inner.south) / 2).toBeCloseTo(
            (outer.north + outer.south) / 2,
            6,
        );
        expect(drawnExtent(small)).toEqual({ w: 600, h: 1000 });
        expect(drawnExtent(big)).toEqual({ w: 1400, h: 1200 });
        expect(inner.west).toBe(400);
        expect(inner.north).toBe(-100);
    });

    it("leaves the group when the image is removed", async () => {
        const scale = createScaleGroup();
        const read = vi.fn();
        const laid = layImage(
            map,
            BY_URL,
            { read, failed: vi.fn() },
            { scale },
        );
        await settle();
        const peer = { nativeZoom: 3, size: { w: 10, h: 10 }, apply: vi.fn() };
        scale.join(peer);
        laid.remove();
        scale.leave(peer);
        expect(scale.zoom()).toBe(0);
    });
});
