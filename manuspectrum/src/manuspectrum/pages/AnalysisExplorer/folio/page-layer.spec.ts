import L from "leaflet";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
    fitPage,
    layPage,
} from "@/manuspectrum/pages/AnalysisExplorer/folio/page-layer.ts";
import { sizedContainer } from "@/manuspectrum/pages/AnalysisExplorer/testing/leaflet.ts";

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
